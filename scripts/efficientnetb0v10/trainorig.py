from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import optparse
import os, sys
import ast
import numpy as np 
import pandas as pd
from PIL import Image
import torch
from torch.optim.lr_scheduler import _LRScheduler
from torch.optim.lr_scheduler import ReduceLROnPlateau
import torch.nn as nn
import torch.nn.functional as F
from sklearn.model_selection import KFold

import os
import cv2
import glob
import numpy as np
import pandas as pd
import torch.optim as optim

from albumentations import Compose, ShiftScaleRotate, Resize
from albumentations.pytorch import ToTensor
from torch.utils.data import Dataset
from sklearn.metrics import log_loss
from torch.utils.data import DataLoader

import cv2
import gc
import random
import logging
import datetime

import torchvision
from torchvision import transforms as T
from torchvision.models.resnet import ResNet, Bottleneck


from albumentations import (Cutout, Compose, Normalize, RandomRotate90, HorizontalFlip,
                           VerticalFlip, ShiftScaleRotate, Transpose, OneOf, IAAAdditiveGaussianNoise,
                           GaussNoise, RandomGamma, RandomContrast, RandomBrightness, HueSaturationValue,
                           RandomCrop, Lambda, NoOp, CenterCrop, Resize
                           )

from tqdm import tqdm
from apex import amp

from apex.parallel import DistributedDataParallel as DDP
from apex.fp16_utils import *
from apex import amp, optimizers
from apex.multi_tensor_apply import multi_tensor_applier


import warnings
warnings.filterwarnings('ignore')

# Print info about environments
parser = optparse.OptionParser()
parser.add_option('-s', '--seed', action="store", dest="seed", help="model seed", default="1234")
parser.add_option('-o', '--fold', action="store", dest="fold", help="Fold for split", default="0")
parser.add_option('-p', '--nbags', action="store", dest="nbags", help="Number of bags for averaging", default="0")
parser.add_option('-e', '--epochs', action="store", dest="epochs", help="epochs", default="5")
parser.add_option('-b', '--batchsize', action="store", dest="batchsize", help="batch size", default="16")
parser.add_option('-r', '--rootpath', action="store", dest="rootpath", help="root directory", default="/share/dhanley2/rsna/")
parser.add_option('-i', '--imgpath', action="store", dest="imgpath", help="root directory", default="data/mount/512X512X6/")
parser.add_option('-w', '--workpath', action="store", dest="workpath", help="Working path", default="densenetv1/weights")
parser.add_option('-f', '--weightsname', action="store", dest="weightsname", help="Weights file name", default="pytorch_model.bin")
parser.add_option('-l', '--lr', action="store", dest="lr", help="learning rate", default="0.00005")
parser.add_option('-g', '--logmsg', action="store", dest="logmsg", help="root directory", default="Recursion-pytorch")
parser.add_option('-c', '--size', action="store", dest="size", help="model size", default="512")
parser.add_option('-a', '--infer', action="store", dest="infer", help="root directory", default="TRN")
parser.add_option('-d', '--beta', action="store", dest="beta", help="beta", default="1.0")
parser.add_option('-j', '--mixup', action="store", dest="mixup", help="Mixup", default="FALSE")
parser.add_option('-k', '--randsample', action="store", dest="randsample", help="Random Sample Fraction of patients with no diagnosis", default="1.0")



options, args = parser.parse_args()
package_dir = options.rootpath
sys.path.append(package_dir)
from logs import get_logger
from utils import dumpobj, loadobj, GradualWarmupScheduler


# Print info about environments
logger = get_logger(options.logmsg, 'INFO') # noqa
logger.info('Cuda set up : time {}'.format(datetime.datetime.now().time()))

device=torch.device('cuda')
logger.info('Device : {}'.format(torch.cuda.get_device_name(0)))
logger.info('Cuda available : {}'.format(torch.cuda.is_available()))
n_gpu = torch.cuda.device_count()
logger.info('Cuda n_gpus : {}'.format(n_gpu ))


logger.info('Load params : time {}'.format(datetime.datetime.now().time()))
for (k,v) in options.__dict__.items():
    logger.info('{}{}'.format(k.ljust(20), v))

SEED = int(options.seed)
SIZE = int(options.size)
EPOCHS = int(options.epochs)
n_epochs = EPOCHS 
lr=float(options.lr)
batch_size = int(options.batchsize)
ROOT = options.rootpath
path_data = os.path.join(ROOT, 'data')
path_img = os.path.join(ROOT, options.imgpath)
WORK_DIR = os.path.join(ROOT, options.workpath)
WEIGHTS_NAME = options.weightsname
fold = int(options.fold)
INFER=options.infer
beta=float(options.beta)
MIXUP=True if options.mixup=='TRUE' else False
RANDSAMPLE=float(options.randsample)

#classes = 1109
device = 'cuda'
print('Data path : {}'.format(path_data))
print('Image path : {}'.format(path_img))

os.environ["TORCH_HOME"] = os.path.join( path_data, 'mount')
logger.info(os.system('$TORCH_HOME'))

# Get image sequences
def bayesMean(df, prior=50, seq = 'Sequence1'):
    globmean = df['any'].mean()
    ctvar = df.groupby(seq)['any'].count()
    meanvar = df.groupby(seq)['any'].mean()
    bayesmean = ((ctvar*meanvar)+(globmean*50))/(ctvar+prior)
    bayesmean.name = 'bayesmean'+seq
    return bayesmean.reset_index()

def sampletrndf(df, epoch, RANDSAMPLE):   
    patgrp = df.groupby('PatientID')['any'].sum()
    patgrp = patgrp[patgrp>0].index.tolist()
    iix = df.PatientID.isin(patgrp)
    return pd.concat([df[~iix].sample(frac=RANDSAMPLE, random_state=epoch), \
                      df[iix]], 0).reset_index(drop = True)

def autocrop(image, threshold=0):
    """Crops any edges below or equal to threshold
    Crops blank image to 1x1.
    Returns cropped image.
    https://stackoverflow.com/questions/13538748/crop-black-edges-with-opencv
    """

    if len(image.shape) == 3:
        flatImage = np.max(image, 2)
    else:
        flatImage = image
    rows = np.where(np.max(flatImage, 0) > threshold)[0]
    cols = np.where(np.max(flatImage, 1) > threshold)[0]
    image = image[cols[0]: cols[-1] + 1, rows[0]: rows[-1] + 1]
    #logger.info(image.shape)
    sqside = max(image.shape)
    imageout = np.zeros((sqside, sqside, 3), dtype = 'uint8')
    imageout[:image.shape[0], :image.shape[1],:] = image.copy()
    return imageout

class IntracranialDataset(Dataset):

    def __init__(self, df, path, labels, transform=None):
        self.path = path
        self.data = df
        self.transform = transform
        self.labels = labels

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        img_name = os.path.join(self.path, self.data.loc[idx, 'Image'] + '.jpg')
        #img = cv2.imread(img_name, cv2.IMREAD_GRAYSCALE)   
        img = cv2.imread(img_name)      
        try:
            img = autocrop(img, threshold=0)  
        except:
            1
            # logger.info('Problem : {}'.format(img_name))      
        img = cv2.resize(img,(SIZE,SIZE))
        #img = np.expand_dims(img, -1)
        if self.transform:       
            augmented = self.transform(image=img)
            img = augmented['image']   
        if self.labels:
            labels = torch.tensor(self.data.loc[idx, label_cols+['bayesmeanSequence1', 'bayesmeanSequence2']])
            return {'image': img, 'labels': labels}    
        else:      
            return {'image': img}

np.random.seed(SEED)
torch.manual_seed(SEED)
torch.cuda.manual_seed(SEED)
if n_gpu > 0:
    torch.cuda.manual_seed_all(SEED)
torch.backends.cudnn.deterministic = True

logger.info('Load Dataframes')
dir_train_img = os.path.join(path_data, 'stage_1_train_images_jpg')
dir_test_img = os.path.join(path_data, 'stage_1_test_images_jpg')

# Parameters
n_classes = 6
label_cols = ['epidural', 'intraparenchymal', 'intraventricular', 'subarachnoid', 'subdural', 'any']

train = pd.read_csv(os.path.join(path_data, 'train.csv.gz'))
test = pd.read_csv(os.path.join(path_data, 'test.csv.gz'))
png = glob.glob(os.path.join(dir_train_img, '*.jpg'))
png = [os.path.basename(png)[:-4] for png in png]
png = np.array(png)
train = train.set_index('Image').loc[png].reset_index()

# get fold
valdf = train[train['fold']==fold].reset_index(drop=True)
trndf = train[train['fold']!=fold].reset_index(drop=True)

trnmdf = pd.read_csv(os.path.join(path_data, 'train_metadata.csv'))
poscols = ['ImagePos{}'.format(i) for i in range(1, 4)]
trnmdf[poscols] = pd.DataFrame(trnmdf['ImagePositionPatient']\
              .apply(lambda x: list(map(float, ast.literal_eval(x)))).tolist())
trnmdf = trnmdf.sort_values(['PatientID']+poscols)\
                [['PatientID', 'SOPInstanceUID']+poscols].reset_index(drop=True)
trnmdf['seq1'] = trnmdf.groupby(['PatientID']).cumcount() + 1
trnmdf['seq2'] = trnmdf[::-1].groupby(['PatientID']).cumcount() + 1
trnseq = trnmdf[['SOPInstanceUID', 'seq1', 'seq2']]
trnseq.columns = ['Image', 'Sequence1', 'Sequence2']
trndf = trndf.merge(trnseq, on='Image')
trndf = trndf.merge(bayesMean(trndf, prior=50, seq = 'Sequence1'), on = 'Sequence1')
trndf = trndf.merge(bayesMean(trndf, prior=50, seq = 'Sequence2'), on = 'Sequence2')
logger.info(trndf.filter(regex='equence').head(10))
    
# Data loaders
transform_train = Compose([
    HorizontalFlip(p=0.5),
    ShiftScaleRotate(shift_limit=0.1, scale_limit=0.01, 
                         rotate_limit=30, p=0.7, border_mode = cv2.BORDER_REPLICATE),
    ToTensor()
])

transform_test= Compose([
    ToTensor()
])

trndataset = IntracranialDataset(trndf, path=dir_train_img, transform=transform_train, labels=True)
valdataset = IntracranialDataset(valdf, path=dir_train_img, transform=transform_test, labels=False)
tstdataset = IntracranialDataset(test, path=dir_test_img, transform=transform_test, labels=False)

num_workers = 16
trnloader = DataLoader(trndataset, batch_size=batch_size, shuffle=True, num_workers=num_workers)
valloader = DataLoader(valdataset, batch_size=batch_size*4, shuffle=False, num_workers=num_workers)
tstloader = DataLoader(tstdataset, batch_size=batch_size*4, shuffle=False, num_workers=num_workers)

from torch.hub import load_state_dict_from_url
from torchvision.models.resnet import ResNet, Bottleneck

'''
# Run below, with internet access
model = torch.hub.load('facebookresearch/WSL-Images', 'resnext101_32x8d_wsl')
torch.save(model, 'resnext101_32x8d_wsl_checkpoint.pth')
'''
#model = torch.load(os.path.join(WORK_DIR, '../../checkpoints/resnext101_32x8d_wsl_checkpoint.pth'))
#model.fc = torch.nn.Linear(2048, n_classes)
torch.hub.list('rwightman/gen-efficientnet-pytorch', force_reload=True)  
model = torch.hub.load('rwightman/gen-efficientnet-pytorch', 'efficientnet_b0', pretrained=True)
#torch.hub.list('darraghdog/gen-efficientnet-pytorch', force_reload=True)  
#model = torch.hub.load('darraghdog/gen-efficientnet-pytorch', 'efficientnet_b0', pretrained=True)
model.classifier = torch.nn.Linear(1280, n_classes+2)
model.to(device)




criterion = torch.nn.BCEWithLogitsLoss()
def criterion(data, targets, criterion = torch.nn.BCEWithLogitsLoss()):
    ''' Define custom loss function for weighted BCE on 'target' column '''
    loss_all = criterion(data[:6], targets[:6])
    loss_any = criterion(data[:,5:6], targets[:,5:6])
    # Try to predict where in the sequence of images we are... auxilliary loss
    loss_seq = criterion(data[:,6:], targets[:,6:])
    return ((loss_all*6 + loss_any*1)/7)*0.8 + 0.2*loss_seq

plist = [{'params': model.parameters(), 'lr': lr}]
optimizer = optim.Adam(plist, lr=lr)

model, optimizer = amp.initialize(model, optimizer, opt_level="O1")

for epoch in range(n_epochs):
    logger.info('Epoch {}/{}'.format(epoch, n_epochs - 1))
    logger.info('-' * 10)
    if INFER not in ['TST', 'VAL']:
        for param in model.parameters():
            param.requires_grad = True
        model.train()    
        tr_loss = 0
        if RANDSAMPLE<1.0:
            trndataset = IntracranialDataset(sampletrndf(trndf, epoch, RANDSAMPLE), \
                                             path=dir_train_img, transform=transform_train, labels=True)
            trnloader = DataLoader(trndataset, batch_size=batch_size, shuffle=True, num_workers=num_workers)            
        for step, batch in enumerate(trnloader):
            if step%1000==0:
                logger.info('Train step {} of {}'.format(step, len(trnloader)))
            x = batch["image"]
            y = batch["labels"]
            x = x.to(device, dtype=torch.float)
            y = y.to(device, dtype=torch.float)
            if MIXUP:
                # Mixup Start
                r = np.random.rand(1)
                if beta > 0 and r < mixup_prob_warmup:
                    # generate mixed sample
                    lam = np.random.beta(beta, beta)
                    rand_index = torch.randperm(x.size()[0]).cuda()
                    y_a = y
                    y_b = y[rand_index]
                    bbx1, bby1, bbx2, bby2 = rand_bbox(x.size(), lam)
                    x = lam * x + (1 - lam) * x[rand_index]
                    x = torch.autograd.Variable(x, requires_grad=True)
                    y_a = torch.autograd.Variable(y_a)
                    y_b = torch.autograd.Variable(y_b)
                    outputs = model(x)
                    loss = criterion(outputs, y_a) * lam + criterion(outputs, y_b) * (1. - lam)
                    del y_a, y_b
                else:
                    x = torch.autograd.Variable(x, requires_grad=True)
                    y = torch.autograd.Variable(y)
                    outputs = model(x)
                    loss = criterion(outputs, y)
            else:
                x = torch.autograd.Variable(x, requires_grad=True)
                y = torch.autograd.Variable(y)
                outputs = model(x)
                loss = criterion(outputs, y)
            with amp.scale_loss(loss, optimizer) as scaled_loss:
                scaled_loss.backward()
            tr_loss += loss.item()
            optimizer.step()
            optimizer.zero_grad()
            del x, y, outputs
        epoch_loss = tr_loss / len(trnloader)
        logger.info('Training Loss: {:.4f}'.format(epoch_loss))
        for param in model.parameters():
            param.requires_grad = False
        output_model_file = 'weights/model_{}_epoch{}.bin'.format(SIZE, epoch)
        torch.save(model.state_dict(), output_model_file)
    else:
        del model
        model = torch.hub.load('rwightman/gen-efficientnet-pytorch', 'efficientnet_b0', pretrained=True)
        #model = torch.hub.load('darraghdog/gen-efficientnet-pytorch', 'efficientnet_b0', pretrained=True)
        model.classifier = torch.nn.Linear(1280, n_classes)
        model.to(device)
        for param in model.parameters():
            param.requires_grad = False
        input_model_file = 'weights/model_{}_epoch{}.bin'.format(SIZE, epoch)
        model.load_state_dict(torch.load(input_model_file))
    model.eval()
    valls = []
    for step, batch in enumerate(valloader):
        if step%1000==0:
            logger.info('Val step {} of {}'.format(step, len(valloader)))
        inputs = batch["image"]
        inputs = inputs.to(device, dtype=torch.float)
        out = model(inputs)
        valls.append(torch.sigmoid(out).detach().cpu().numpy()[:,:6])
    weights = ([1, 1, 1, 1, 1, 2] * valdf.shape[0])
    yact = valdf[label_cols].values.flatten()
    ypred = np.concatenate(valls, 0).flatten()
    valloss = log_loss(yact, ypred, sample_weight = weights)
    logger.info('Epoch {} logloss {}'.format(epoch, valloss))
    valpreddf = pd.DataFrame(np.concatenate(valls, 0), columns = label_cols)
    valdf.to_csv('val_act_fold{}.csv.gz'.format(fold), compression='gzip', index = False)
    valpreddf.to_csv('val_pred_{}_fold{}_epoch{}_samp{}.csv.gz'.format(SIZE, fold, epoch, RANDSAMPLE), compression='gzip', index = False)
    if INFER == 'TST':
        tstls = []
        for step, batch in enumerate(tstloader):
            if step%1000==0:
                logger.info('Tst step {} of {}'.format(step, len(tstloader)))
            inputs = batch["image"]
            inputs = inputs.to(device, dtype=torch.float)
            out = model(inputs)
            tstls.append(torch.sigmoid(out).detach().cpu().numpy()[:,:6])
        tstpreddf = pd.DataFrame(np.concatenate(tstls, 0), columns = label_cols)
        test.to_csv('tst_act_fold.csv.gz', compression='gzip', index = False)
        tstpreddf.to_csv('tst_pred_{}_fold{}_epoch{}_samp{}.csv.gz'.format(SIZE, fold, epoch, RANDSAMPLE), compression='gzip', index = False)
