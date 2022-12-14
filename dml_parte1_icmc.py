import torch
import torchvision
import torchvision.transforms as transforms
import torch.nn as nn
import torch.optim as optim

from tqdm import tqdm
import numpy as np
import pdb
import time

torch.cuda.get_device_properties(0)

import os

"""#Parameters"""

n_classes = 10
emb_size = 512
lr = 0.0005
batch_size = 512
device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

"""# Prepare data loaders"""

os.chdir('/content/drive/MyDrive/tutorial_dml')

transform = transforms.Compose([transforms.Resize((50,50)),
                                transforms.ToTensor(),
                                transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
                            ])

ds_train = torchvision.datasets.CIFAR10('./',train=True,transform=transform,download=True)
ds_test  = torchvision.datasets.CIFAR10('./',train=False,transform=transform,download=True)

n_classes = len(ds_train.classes)

dl_train = torch.utils.data.DataLoader(ds_train,batch_size=batch_size,drop_last=True)
dl_test  = torch.utils.data.DataLoader(ds_test,batch_size=batch_size,drop_last=True)

x,y = next(iter(dl_train))

x.shape,y.shape

y[0]

ds_train.classes

"""# Prepare model"""

model = torchvision.models.resnet50(pretrained=True)

model

import torchsummary

emb_size

model.fc = nn.Linear(model.fc.in_features,emb_size)

model.to(device)

"""##  Exercício 1: modifique as redes """

model = torchvision.models.mobilenet_v3_small(pretrained=True)

model

model.classifier = nn.Linear(576,512)

model

x,y = next(iter(dl_train))

x.shape,y.shape

"""# Loss Function"""

from torch import distributed
world_size = 1
rank = 0
distributed.init_process_group(
    backend="nccl",
    init_method="tcp://127.0.0.1:12584",
    rank=rank,
    world_size=world_size,
)

import torch
import math


class CombinedMarginLoss(torch.nn.Module):
    def __init__(self, 
                 s, 
                 m1,
                 m2,
                 m3,
                 interclass_filtering_threshold=0):
        super().__init__()
        self.s = s
        self.m1 = m1
        self.m2 = m2
        self.m3 = m3
        self.interclass_filtering_threshold = interclass_filtering_threshold
        
        # For ArcFace
        self.cos_m = math.cos(self.m2)
        self.sin_m = math.sin(self.m2)
        self.theta = math.cos(math.pi - self.m2)
        self.sinmm = math.sin(math.pi - self.m2) * self.m2
        self.easy_margin = False


    def forward(self, logits, labels):
        index_positive = torch.where(labels != -1)[0]

        if self.interclass_filtering_threshold > 0:
            with torch.no_grad():
                dirty = logits > self.interclass_filtering_threshold
                dirty = dirty.float()
                mask = torch.ones([index_positive.size(0), logits.size(1)], device=logits.device)
                mask.scatter_(1, labels[index_positive], 0)
                dirty[index_positive] *= mask
                tensor_mul = 1 - dirty    
            logits = tensor_mul * logits

        target_logit = logits[index_positive, labels[index_positive].view(-1)]

        if self.m1 == 1.0 and self.m3 == 0.0:
            sin_theta = torch.sqrt(1.0 - torch.pow(target_logit, 2))
            cos_theta_m = target_logit * self.cos_m - sin_theta * self.sin_m  # cos(target+margin)
            if self.easy_margin:
                final_target_logit = torch.where(
                    target_logit > 0, cos_theta_m, target_logit)
            else:
                final_target_logit = torch.where(
                    target_logit > self.theta, cos_theta_m, target_logit - self.sinmm)
            logits[index_positive, labels[index_positive].view(-1)] = final_target_logit
            logits = logits * self.s
        
        elif self.m3 > 0:
            final_target_logit = target_logit - self.m3
            logits[index_positive, labels[index_positive].view(-1)] = final_target_logit
            logits = logits * self.s
        else:
            raise        

        return logits

class ArcFace(torch.nn.Module):
    """ ArcFace (https://arxiv.org/pdf/1801.07698v1.pdf):
    """
    def __init__(self, s=64.0, margin=0.5):
        super(ArcFace, self).__init__()
        self.scale = s
        self.cos_m = math.cos(margin)
        self.sin_m = math.sin(margin)
        self.theta = math.cos(math.pi - margin)
        self.sinmm = math.sin(math.pi - margin) * margin
        self.easy_margin = False


    def forward(self, logits: torch.Tensor, labels: torch.Tensor):
        index = torch.where(labels != -1)[0]
        target_logit = logits[index, labels[index].view(-1)]

        sin_theta = torch.sqrt(1.0 - torch.pow(target_logit, 2))
        cos_theta_m = target_logit * self.cos_m - sin_theta * self.sin_m  # cos(target+margin)
        if self.easy_margin:
            final_target_logit = torch.where(
                target_logit > 0, cos_theta_m, target_logit)
        else:
            final_target_logit = torch.where(
                target_logit > self.theta, cos_theta_m, target_logit - self.sinmm)

        logits[index, labels[index].view(-1)] = final_target_logit
        logits = logits * self.scale
        return logits


class CosFace(torch.nn.Module):
    def __init__(self, s=64.0, m=0.40):
        super(CosFace, self).__init__()
        self.s = s
        self.m = m

    def forward(self, logits: torch.Tensor, labels: torch.Tensor):
        index = torch.where(labels != -1)[0]
        target_logit = logits[index, labels[index].view(-1)]
        final_target_logit = target_logit - self.m
        logits[index, labels[index].view(-1)] = final_target_logit
        logits = logits * self.s
        return logits

import math
from typing import Callable

import torch
from torch import distributed
from torch.nn.functional import linear, normalize


class PartialFC_V2(torch.nn.Module):
    """
    https://arxiv.org/abs/2203.15565
    A distributed sparsely updating variant of the FC layer, named Partial FC (PFC).
    When sample rate less than 1, in each iteration, positive class centers and a random subset of
    negative class centers are selected to compute the margin-based softmax loss, all class
    centers are still maintained throughout the whole training process, but only a subset is
    selected and updated in each iteration.
    .. note::
        When sample rate equal to 1, Partial FC is equal to model parallelism(default sample rate is 1).
    Example:
    --------
    >>> module_pfc = PartialFC(embedding_size=512, num_classes=8000000, sample_rate=0.2)
    >>> for img, labels in data_loader:
    >>>     embeddings = net(img)
    >>>     loss = module_pfc(embeddings, labels)
    >>>     loss.backward()
    >>>     optimizer.step()
    """
    _version = 2

    def __init__(
        self,
        margin_loss: Callable,
        embedding_size: int,
        num_classes: int,
        sample_rate: float = 1.0,
        fp16: bool = False,
    ):
        """
        Paramenters:
        -----------
        embedding_size: int
            The dimension of embedding, required
        num_classes: int
            Total number of classes, required
        sample_rate: float
            The rate of negative centers participating in the calculation, default is 1.0.
        """
        super(PartialFC_V2, self).__init__()
        assert (
            distributed.is_initialized()
        ), "must initialize distributed before create this"
        self.rank = distributed.get_rank()
        self.world_size = distributed.get_world_size()

        self.dist_cross_entropy = DistCrossEntropy()
        self.embedding_size = embedding_size
        self.sample_rate: float = sample_rate
        self.fp16 = fp16
        self.num_local: int = num_classes // self.world_size + int(
            self.rank < num_classes % self.world_size
        )
        self.class_start: int = num_classes // self.world_size * self.rank + min(
            self.rank, num_classes % self.world_size
        )
        self.num_sample: int = int(self.sample_rate * self.num_local)
        self.last_batch_size: int = 0

        self.is_updated: bool = True
        self.init_weight_update: bool = True
        self.weight = torch.nn.Parameter(torch.normal(0, 0.01, (self.num_local, embedding_size)))

        # margin_loss
        if isinstance(margin_loss, Callable):
            self.margin_softmax = margin_loss
        else:
            raise

    def sample(self, labels, index_positive):
        """
            This functions will change the value of labels
            Parameters:
            -----------
            labels: torch.Tensor
                pass
            index_positive: torch.Tensor
                pass
            optimizer: torch.optim.Optimizer
                pass
        """
        with torch.no_grad():
            positive = torch.unique(labels[index_positive], sorted=True).cuda()
            if self.num_sample - positive.size(0) >= 0:
                perm = torch.rand(size=[self.num_local]).cuda()
                perm[positive] = 2.0
                index = torch.topk(perm, k=self.num_sample)[1].cuda()
                index = index.sort()[0].cuda()
            else:
                index = positive
            self.weight_index = index

            labels[index_positive] = torch.searchsorted(index, labels[index_positive])

        return self.weight[self.weight_index]

    def forward(
        self,
        local_embeddings: torch.Tensor,
        local_labels: torch.Tensor,
    ):
        """
        Parameters:
        ----------
        local_embeddings: torch.Tensor
            feature embeddings on each GPU(Rank).
        local_labels: torch.Tensor
            labels on each GPU(Rank).
        Returns:
        -------
        loss: torch.Tensor
            pass
        """
        local_labels.squeeze_()
        local_labels = local_labels.long()

        batch_size = local_embeddings.size(0)
        if self.last_batch_size == 0:
            self.last_batch_size = batch_size
        assert self.last_batch_size == batch_size, (
            f"last batch size do not equal current batch size: {self.last_batch_size} vs {batch_size}")

        _gather_embeddings = [
            torch.zeros((batch_size, self.embedding_size)).cuda()
            for _ in range(self.world_size)
        ]
        _gather_labels = [
            torch.zeros(batch_size).long().cuda() for _ in range(self.world_size)
        ]
        _list_embeddings = AllGather(local_embeddings, *_gather_embeddings)
        distributed.all_gather(_gather_labels, local_labels)

        embeddings = torch.cat(_list_embeddings)
        labels = torch.cat(_gather_labels)

        labels = labels.view(-1, 1)
        index_positive = (self.class_start <= labels) & (
            labels < self.class_start + self.num_local
        )
        labels[~index_positive] = -1
        labels[index_positive] -= self.class_start

        if self.sample_rate < 1:
            weight = self.sample(labels, index_positive)
        else:
            weight = self.weight

        with torch.cuda.amp.autocast(self.fp16):
            norm_embeddings = normalize(embeddings)
            norm_weight_activated = normalize(weight)
            logits = linear(norm_embeddings, norm_weight_activated)
        if self.fp16:
            logits = logits.float()
        logits = logits.clamp(-1, 1)

        logits = self.margin_softmax(logits, labels)
        loss = self.dist_cross_entropy(logits, labels)
        return loss


class DistCrossEntropyFunc(torch.autograd.Function):
    """
    CrossEntropy loss is calculated in parallel, allreduce denominator into single gpu and calculate softmax.
    Implemented of ArcFace (https://arxiv.org/pdf/1801.07698v1.pdf):
    """

    @staticmethod
    def forward(ctx, logits: torch.Tensor, label: torch.Tensor):
        """ """
        batch_size = logits.size(0)
        # for numerical stability
        max_logits, _ = torch.max(logits, dim=1, keepdim=True)
        # local to global
        distributed.all_reduce(max_logits, distributed.ReduceOp.MAX)
        logits.sub_(max_logits)
        logits.exp_()
        sum_logits_exp = torch.sum(logits, dim=1, keepdim=True)
        # local to global
        distributed.all_reduce(sum_logits_exp, distributed.ReduceOp.SUM)
        logits.div_(sum_logits_exp)
        index = torch.where(label != -1)[0]
        # loss
        loss = torch.zeros(batch_size, 1, device=logits.device)
        loss[index] = logits[index].gather(1, label[index])
        distributed.all_reduce(loss, distributed.ReduceOp.SUM)
        ctx.save_for_backward(index, logits, label)
        return loss.clamp_min_(1e-30).log_().mean() * (-1)

    @staticmethod
    def backward(ctx, loss_gradient):
        """
        Args:
            loss_grad (torch.Tensor): gradient backward by last layer
        Returns:
            gradients for each input in forward function
            `None` gradients for one-hot label
        """
        (
            index,
            logits,
            label,
        ) = ctx.saved_tensors
        batch_size = logits.size(0)
        one_hot = torch.zeros(
            size=[index.size(0), logits.size(1)], device=logits.device
        )
        one_hot.scatter_(1, label[index], 1)
        logits[index] -= one_hot
        logits.div_(batch_size)
        return logits * loss_gradient.item(), None


class DistCrossEntropy(torch.nn.Module):
    def __init__(self):
        super(DistCrossEntropy, self).__init__()

    def forward(self, logit_part, label_part):
        return DistCrossEntropyFunc.apply(logit_part, label_part)


class AllGatherFunc(torch.autograd.Function):
    """AllGather op with gradient backward"""

    @staticmethod
    def forward(ctx, tensor, *gather_list):
        gather_list = list(gather_list)
        distributed.all_gather(gather_list, tensor)
        return tuple(gather_list)

    @staticmethod
    def backward(ctx, *grads):
        grad_list = list(grads)
        rank = distributed.get_rank()
        grad_out = grad_list[rank]

        dist_ops = [
            distributed.reduce(grad_out, rank, distributed.ReduceOp.SUM, async_op=True)
            if i == rank
            else distributed.reduce(
                grad_list[i], i, distributed.ReduceOp.SUM, async_op=True
            )
            for i in range(distributed.get_world_size())
        ]
        for _op in dist_ops:
            _op.wait()

        grad_out *= len(grad_list)  # cooperate with distributed loss function
        return (grad_out, *[None for _ in range(len(grad_list))])


AllGather = AllGatherFunc.apply

margin_loss = CombinedMarginLoss(
    64,
    1.0,
    0.5,
    0,
    0
)
loss_function = PartialFC_V2(margin_loss=margin_loss,embedding_size=emb_size, num_classes=n_classes, sample_rate=0.2)
loss_function.train().cuda()

"""# Training """

opt       = optim.AdamW(model.parameters(),lr=lr)
stop = False

model.to(device)

epoch = 0
patience = 10
start_time = time.perf_counter()
batch_loss = []
batch_loss_test = []
best_loss = 10000

start_time = time.perf_counter()
patience = 10
stop = False
while(not stop):
    batch_list_loss = []
    batch_iterator = tqdm(dl_train)
    for i,(x,y)  in enumerate(batch_iterator):
        x = x.to(device)
        y = y.to(device)
        embeddings = model(x)
        loss = loss_function(embeddings,y)

        opt.zero_grad()
        loss.backward()
        batch_list_loss.append(loss.item())
        opt.step()
    batch_loss.append(np.mean(batch_list_loss))
    print("training loss ",batch_loss[-1])

    with torch.no_grad():
        batch_list_loss = []
        for i,(x,y) in enumerate(dl_test):
            x = x.to(device)
            y = y.to(device)
            embeddings = model(x)
            loss = loss_function(embeddings,y)
            batch_list_loss.append(loss.item())
        batch_loss_test.append(np.mean(batch_list_loss))
    print("test loss ",batch_loss_test[-1])
    if batch_loss_test[-1] < best_loss:
        print("saving model")
        patience_wait = patience
        best_loss = batch_loss_test[-1]
        save_model = {'model':model.state_dict(),'opt':opt.state_dict(),'loss_training':batch_list_loss}
        torch.save(save_model,'best_model_v1.pth')
    patience_wait -= 1
    if patience_wait == 0:
        stop = True



    

    epoch +=1
end_time = time.perf_counter()

save_model = {'model':model.state_dict(),'opt':opt.state_dict(),'loss_training':batch_list_loss}

torch.save(save_model,'last_run.pth')

saved_model = torch.load('best_model_v1.pth')

model.load_state_dict(saved_model['model'])

"""# Evaluation"""

with torch.no_grad():
    batch_list_loss = []
    train_embeddings = []
    train_y          = []
    test_embeddings = []
    test_y          = []
    for i,(x,y) in enumerate(dl_train):
        x = x.to(device)
        y = y.to(device)
        embeddings = model(x)
        train_embeddings.append(embeddings)
        train_y.append(y)

    for i,(x,y) in enumerate(dl_test):
        x = x.to(device)
        y = y.to(device)
        embeddings = model(x)
        test_embeddings.append(embeddings)
        test_y.append(y)

jtrain_emb = torch.cat(train_embeddings,axis=0)
jtest_emb = torch.cat(test_embeddings,axis=0)

jtrain_emb.shape

xtrain = jtrain_emb.cpu().numpy()
xtest  = jtest_emb.cpu().numpy()

ytrain = torch.cat(train_y).cpu().numpy()
ytest  = torch.cat(test_y).cpu().numpy()

import sklearn.neighbors

knn = sklearn.neighbors.KNeighborsClassifier(n_neighbors=1,weights='distance')

knn.fit(xtrain,ytrain)

pred = knn.predict(xtest)
#predp = knn.predict_proba(xtest)

import sklearn.metrics as metrics

print("precision ", metrics.precision_score(ytest,pred,average='macro'))
print("recall    ", metrics.recall_score(ytest,pred,average='macro'))
print("f1        ", metrics.f1_score(ytest,pred,average='macro'))

print(metrics.classification_report(ytest,pred))

print(metrics.top_k_accuracy_score(ytest,predp,k=5))

ds_train.classes

"""# Pytorch metric learning"""

from pytorch_metric_learning import distances, losses, miners, reducers, testers
from pytorch_metric_learning.utils.accuracy_calculator import AccuracyCalculator

distance = distances.CosineSimilarity()
reducer = reducers.ThresholdReducer(low=0)
loss_function = losses.ArcFaceLoss(margin=.2, distance=distance,reducer=reducer,num_classes=n_classes ,embedding_size =emb_size )