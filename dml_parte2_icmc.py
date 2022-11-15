# -*- coding: utf-8 -*-
"""DML_parte2_icmc

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1PhkUwYkmOhWTnRFn8TT1y8pcKxOsDl9N
"""

import cv2
import imutils
import numpy as np
import os
import sys
import dlib
from google.colab.patches import cv2_imshow
from PIL import Image,ImageStat

!pip install python-telegram-bot --upgrade

main_dir = '/content/drive/MyDrive/tutorial_dml'



os.chdir(main_dir)

"""# Alinhamento e crop das faces"""

!wget -N http://dlib.net/files/shape_predictor_5_face_landmarks.dat.bz2

!bunzip2 "shape_predictor_5_face_landmarks.dat.bz2"

!ls

face_file_path = main_dir+"/pessoas/IMG_20220827_155011.jpg"

face_file_path.split('/')[-1]

!ls

if not os.path.isdir('cropped'):os.mkdir('cropped')

predictor_path = "shape_predictor_5_face_landmarks.dat"
detector = dlib.get_frontal_face_detector()
sp = dlib.shape_predictor(predictor_path)

# Load the image using Dlib

def crop_images():
    for file_name in os.listdir('pessoas'):
        face_file_path = main_dir+f'/pessoas/{file_name}'
        print(face_file_path)
        img = dlib.load_rgb_image(face_file_path)

        # Ask the detector to find the bounding boxes of each face. The 1 in the
        # second argument indicates that we should upsample the image 1 time. This
        # will make everything bigger and allow us to detect more faces.
        dets = detector(img, 1)

        num_faces = len(dets)
        if num_faces == 0:
            print("Sorry, there were no faces found in '{}'".format(face_file_path))
        else:
            # Find the 5 face landmarks we need to do the alignment.
            faces = dlib.full_object_detections()
            for detection in dets:
                faces.append(sp(img, detection))



            # Get the aligned face images
            # Optionally: 
            images = dlib.get_face_chips(img, faces, size=160, padding=0.25)
            #images = dlib.get_face_chips(img, faces, size=320)
            for i,image in enumerate(images):
                #im_pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                im_pil = Image.fromarray(image)
                im_pil.save(f"cropped/{face_file_path.split('/')[-1].replace('.jpg','')}_{i}.jpg")
                

# It is also possible to get a single chip
#image = dlib.get_face_chip(img, faces[0])

#crop_images()

"""Após o crop, separe as faces por pessoa onde cada pessoa é uma pasta

    tutorial_dml/familia/takashi
                         /patricia
                         /naomi
                         /takeo
                         /pai
                         /mae    
"""



"""# Identificação das faces

## Preparação do ambiente
"""

import os

from google.colab import drive
drive.mount('/content/drive')

os.chdir('/content/drive/MyDrive/tutorial_dml/')

!ls

!git clone https://github.com/deepinsight/insightface.git

os.chdir("/content/drive/MyDrive/tutorial_dml/insightface/recognition/arcface_torch")

!ls

!pip install -r requirement.txt

"""## Carga do modelo"""

import argparse

import cv2
import numpy as np
import torch

from  import get_model

model = get_model('r50', fp16=False)

model

!gdown 17dp-EUhvX4K-g8s0ce8ODRNTiaYjTC_D

model.load_state_dict(torch.load('backbone.pth'))

"""## Preparação do conjunto de dados"""

import torchvision
import torchvision.transforms as transforms

transform = transforms.Compose([transforms.Resize((130,130)),
                                transforms.CenterCrop((112,112)),
                                transforms.ToTensor(),
                                transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
                            ])

ds = torchvision.datasets.ImageFolder("/content/drive/MyDrive/tutorial_dml/familia3",transform=transform)

len(ds)

dl = torch.utils.data.DataLoader(ds,batch_size=len(ds))

model.eval()

x,y = next(iter(dl))

x.shape

"""## Construção dos embeddings"""

pred = model(x)

pred.shape

xall = np.asarray(pred.tolist())

"""## Splits de treino e teste"""

from sklearn.model_selection import train_test_split

xtrain, xtest, ytrain, ytest = train_test_split(xall, y, test_size=0.33, random_state=42,stratify=np.array(y))



"""## Treino e execução do knn"""

import sklearn.neighbors

knn = sklearn.neighbors.KNeighborsClassifier(n_neighbors=1,weights='distance')

knn.fit(xtrain,ytrain)

pred = knn.predict(xtest)



"""## Avaliação do modelo"""

import sklearn.metrics as metrics

print(metrics.classification_report(ytest,pred))

ds.classes

print(metrics.confusion_matrix(ytest,pred))



"""# Chatbot"""



!pip install python-telegram-bot --upgrade

from telegram.ext import Updater, Filters, MessageHandler, CommandHandler
import requests
import re
import torchvision.transforms as transforms
from PIL import Image,ImageStat

knn.fit(xall, y)

predictor_path = main_dir+ "/shape_predictor_5_face_landmarks.dat"
detector = dlib.get_frontal_face_detector()
sp = dlib.shape_predictor(predictor_path)

# Load the image using Dlib

def crop_images(image_file):

    face_file_path = image_file
    print(face_file_path)
    img = dlib.load_rgb_image(face_file_path)

    # Ask the detector to find the bounding boxes of each face. The 1 in the
    # second argument indicates that we should upsample the image 1 time. This
    # will make everything bigger and allow us to detect more faces.
    dets = detector(img, 1)
    crop_found = []
    num_faces = len(dets)
    if num_faces == 0:
        print("Sorry, there were no faces found in '{}'".format(face_file_path))
    else:
        # Find the 5 face landmarks we need to do the alignment.
        faces = dlib.full_object_detections()
        for detection in dets:
            faces.append(sp(img, detection))



        # Get the aligned face images
        # Optionally: 
        images = dlib.get_face_chips(img, faces, size=160, padding=0.25)
        #images = dlib.get_face_chips(img, faces, size=320)
        for i,image in enumerate(images):
            #im_pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            im_pil = Image.fromarray(image)
            crop_found.append(im_pil)
    return crop_found

file_name = "IMG_20220827_155011.jpg"



crops = crop_images("/content/drive/MyDrive/tutorial_dml/pessoas/"+file_name)

crops[0]

nomes = np.asarray(ds.classes)

def get_person_ids(crops):
    imglist = []
    for img in crops:
        imglist.append(transform(img).unsqueeze(0))
    x = torch.cat(imglist,axis=0)
    embeddings = model(x)
    embeddings = np.asarray(embeddings.tolist())
    prob_pessoas = knn.predict_proba(embeddings)
    id_pessoas = prob_pessoas.argmax(axis=1)
    return nomes[id_pessoas]

pessoas_identificadas=get_person_ids(crops)

print(f'{pessoas_identificadas}')

len(crops)

nomes = np.asarray(ds.classes)

dir_bot = "/content/drive/MyDrive/tutorial_dml/imgs_recebidas"

dir_pessoas = "/content/drive/MyDrive/tutorial_dml/imgs_pessoas"

if not os.path.isdir(dir_bot): os.mkdir(dir_bot)
if not os.path.isdir(dir_pessoas): os.mkdir(dir_pessoas)

def encontra_pessoas(image_file):
    crops = crop_images(dir_bot+os.sep+image_file)
    for i,img in enumerate(crops):
        img.save(dir_pessoas+f"/{i}.jpg")

    return get_person_ids(crops)

import pdb

def image_handler(update, context):
    file = update.message.photo[-1].file_id
    obj = context.bot.get_file(file)
    os.chdir(dir_bot)
    path = obj.download()
    pessoas_identificadas = encontra_pessoas(path)
    print(pessoas_identificadas)
    for i, nome_pessoa in enumerate(pessoas_identificadas):
        update.message.reply_photo(open(dir_pessoas+f"/{i}.jpg","rb"))
        update.message.reply_text(f'{nome_pessoa}')

def start(update, context):
  return update.message.reply_text('Seja bem vindo ao reconhecedor facial ')

def main():
    updater = Updater('5112886344:AAE2aG449Ufl8bT-Ojk_v-nHT-WT0mc5xJA')
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.photo, image_handler))
    dp.add_handler(CommandHandler('start', start))
    updater.start_polling()
    updater.idle()

main()

"""https://github.com/deepinsight/insightface/tree/master/recognition/arcface_torch"""



