#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Oct  2 20:53:27 2019

@author: dhanley2
"""
import numpy as np
import math
import pandas as pd
import os
from sklearn.metrics import log_loss
import ast
import pickle

def dumpobj(file, obj):
    with open(file, 'wb') as handle:
        pickle.dump(obj, handle, protocol=pickle.HIGHEST_PROTOCOL)
        
def loadobj(file):
    with open(file, 'rb') as handle:
        return pickle.load(handle)

label_cols = ['epidural', 'intraparenchymal', 'intraventricular', 'subarachnoid', 'subdural', 'any']

path='/Users/dhanley2/Documents/Personal/rsna/eda'

trnmdf = pd.read_csv(os.path.join(path, '../data/train_metadata.csv'))
poscols = ['ImagePos{}'.format(i) for i in range(1, 4)]
trnmdf[poscols] = pd.DataFrame(trnmdf['ImagePositionPatient']\
              .apply(lambda x: list(map(float, ast.literal_eval(x)))).tolist())
trnmdf = trnmdf.sort_values(['PatientID']+poscols).reset_index(drop=True)
trnmdf.iloc[0]
trnmdf[['SOPInstanceUID', 'ImagePos1', 'ImagePos2', 'ImagePos3']].head()

poslabels = ['ImagePos1', 'ImagePos2', 'ImagePos3']
trnmdf[['ImagePos1', 'ImagePos2', 'ImagePos3']].shift(1).head()
trnmdf[['{}_lag'.format(i) for i in poslabels]] = trnmdf[poslabels] - trnmdf[poslabels].shift(1)
ix = trnmdf[['PatientID', 'ImagePos1', 'ImagePos2']].shift(1) != trnmdf[['PatientID', 'ImagePos1', 'ImagePos2']]
trnmdf .loc[np.where(ix.sum(1)!=0)[0], ['{}_lag'.format(i) for i in poslabels]] = 0


trnmdf.filter(like='ImagePos')
trnmdf['ImagePos3'].hist(bins=100) 

trnmdf = trnmdf.sort_values(['PatientID']+poscols)\
                [['PatientID', 'SOPInstanceUID']+poscols].reset_index(drop=True)
trnmdf['seq'] = trnmdf.groupby(['PatientID']).cumcount() + 1

wts3 = np.array([0.6, 1.8, 0.6])
#wts5 = np.array([0.5, 1., 2., 1., 0.5])
def f(w3):                        
    def g(x):
        if len(x)>2:
            return (w3*x).mean()
        else:
            return x.mean()
    return g

 

# Ct 0 LLoss 0.07719 RmeanLLoss 0.07233 LLoss Avg 0.07719 Rmean Avg 0.07233
ypredls = []
ypredrmeanls = []
for fold in [0]:
    yact = pd.read_csv(os.path.join(path, 'val_act_fold{}.csv.gz'.format(fold )))
    yactf = yact[label_cols].values.flatten()
    for epoch in range(0, 1):
        #ypred = pd.read_csv(os.path.join(path, 'seq/se50v3/val_pred_sz448_wt448_fold{}_epoch{}.csv.gz'.format(fold ,epoch)))
        #ypred = pd.read_csv(os.path.join(path, '../../eda/seq/se100v1/val_pred_sz384_wt384_fold{}_epoch{}.csv.gz'.format(fold ,epoch)))
        #ypred = pd.read_csv(os.path.join(path, 'seq/v6/val_pred_sz384_wt384_fold{}_epoch{}.csv.gz'.format(fold ,epoch)))
        ypred = pd.read_csv(os.path.join(path, 'seq/v13/val_pred_sz480_wt480_fold{}_epoch{}.csv.gz'.format(fold ,epoch)))
        ypred[['Image', 'PatientID']] =  yact[['Image', 'PatientID']]
        ypred = ypred.merge(trnmdf[['SOPInstanceUID', 'seq']], left_on='Image', right_on ='SOPInstanceUID', how='inner')
        ypred = ypred.sort_values(['PatientID', 'seq'])
        ypredrmean = ypred.groupby('PatientID')[label_cols]\
                        .rolling(3, center = True, min_periods=1).apply(f(wts3)).values
        ypredrmean = pd.DataFrame(ypredrmean, index = ypred.index.tolist(), columns = label_cols )
        ypred = ypred.sort_index()
        ypredrmean = ypredrmean.sort_index()
        #ypred = pd.read_csv(os.path.join(path, 'val_pred_256_fold0_epoch{}_samp1.0.csv.gz'.format(i)))
        weights = ([1, 1, 1, 1, 1, 2] * yact.shape[0])
        ypred = ypred[label_cols].values.flatten()
        ypredrmean = ypredrmean[label_cols].values.flatten()
        ypredls.append(ypred)    
        ypredrmeanls.append(ypredrmean)
        print('Epoch {} LLoss {:.5f} RmeanLLoss {:.5f} LLoss Avg {:.5f} Rmean Avg {:.5f}'.format(1+epoch, \
            log_loss(yactf, ypred, sample_weight = weights), \
            log_loss(yactf, ypredrmean, sample_weight = weights), \
            log_loss(yactf, sum(ypredls)/len(ypredls), sample_weight = weights), \
            log_loss(yactf, sum(ypredrmeanls)/len(ypredrmeanls), sample_weight = weights)))   
 

'''
V6
Epoch 1 LLoss 0.07719 RmeanLLoss 0.07233 LLoss Avg 0.07719 Rmean Avg 0.07233
Epoch 2 LLoss 0.07427 RmeanLLoss 0.06979 LLoss Avg 0.07199 Rmean Avg 0.06896
Epoch 3 LLoss 0.07323 RmeanLLoss 0.06732 LLoss Avg 0.06965 Rmean Avg 0.06690
Epoch 4 LLoss 0.07191 RmeanLLoss 0.06686 LLoss Avg 0.06829 Rmean Avg 0.06576
Epoch 5 LLoss 0.07473 RmeanLLoss 0.06854 LLoss Avg 0.06758 Rmean Avg 0.06520
Epoch 6 LLoss 0.07560 RmeanLLoss 0.06861 LLoss Avg 0.06692 Rmean Avg 0.06464
Epoch 7 LLoss 0.07335 RmeanLLoss 0.06680 LLoss Avg 0.06623 Rmean Avg 0.06405
'''                     

'''
V11
Epoch 1 LLoss 0.07518 RmeanLLoss 0.06948 LLoss Avg 0.07518 Rmean Avg 0.06948
Epoch 2 LLoss 0.07234 RmeanLLoss 0.06820 LLoss Avg 0.06998 Rmean Avg 0.06666
Epoch 3 LLoss 0.07338 RmeanLLoss 0.06727 LLoss Avg 0.06826 Rmean Avg 0.06524
Epoch 4 LLoss 0.07338 RmeanLLoss 0.06743 LLoss Avg 0.06734 Rmean Avg 0.06462
Epoch 5 LLoss 0.07416 RmeanLLoss 0.06716 LLoss Avg 0.06654 Rmean Avg 0.06395
Epoch 6 LLoss 0.07358 RmeanLLoss 0.06665 LLoss Avg 0.06600 Rmean Avg 0.06346
Epoch 7 LLoss 0.07475 RmeanLLoss 0.06749 LLoss Avg 0.06571 Rmean Avg 0.06324
Epoch 8 LLoss 0.07957 RmeanLLoss 0.06837 LLoss Avg 0.06556 Rmean Avg 0.06299
Epoch 9 LLoss 0.13663 RmeanLLoss 0.08806 LLoss Avg 0.06573 Rmean Avg 0.06289
'''

'''
Epoch 2 LLoss 0.07234 RmeanLLoss 0.06820 LLoss Avg 0.07234 Rmean Avg 0.06820
Epoch 3 LLoss 0.07338 RmeanLLoss 0.06727 LLoss Avg 0.06911 Rmean Avg 0.06569
Epoch 4 LLoss 0.07338 RmeanLLoss 0.06743 LLoss Avg 0.06785 Rmean Avg 0.06483
Epoch 5 LLoss 0.07416 RmeanLLoss 0.06716 LLoss Avg 0.06683 Rmean Avg 0.06399
Epoch 6 LLoss 0.07358 RmeanLLoss 0.06665 LLoss Avg 0.06627 Rmean Avg 0.06348
Epoch 7 LLoss 0.07475 RmeanLLoss 0.06749 LLoss Avg 0.06593 Rmean Avg 0.06323
Epoch 8 LLoss 0.07957 RmeanLLoss 0.06837 LLoss Avg 0.06575 Rmean Avg 0.06295
Epoch 9 LLoss 0.13663 RmeanLLoss 0.08806 LLoss Avg 0.06601 Rmean Avg 0.06289
'''
