## define trainer class and methods
import sys
import tqdm
import torch.nn as nn
import numpy as np
import os
import matplotlib.pyplot as plt
import copy
import pathlib
import time
from time import *
from time import time
from PIL import Image

sys.path.append(os.path.join(pathlib.Path(__file__).parent.absolute(),'../Network'))

import torch
import unet_model as model
from torch import optim
import loss as Loss
import evaluator as eval
from Augmentation import Augmentor
from geometric_transform import GeometricTransform, MockTransform
from trainer_unet import Trainer as UnetTrainer
import datetime


class Trainer(UnetTrainer):

    def __init__(self, args, Loader, device):

        super(Trainer, self).__init__(args, Loader, device)
        self.rampup_epoch = args.RampupEpoch    # rampup epoch
        self.rampup_type = args.RampupType  # rampup type
        self.W = self.WeightRampup(self.rampup_type,self.rampup_epoch)    # rampup weight
        self.alpha = args.Alpha  # ema moving average weight

        self.val_micro_Dice = -1.
        self.te_micro_Dice = -1.

        self.val_macro_Dice = -1.
        self.te_macro_Dice = -1.

        self.best_val_Dice = -1

        self.best_te_macro_Dice = -1.
        self.best_te_micro_Dice = -1.

        # loss_tr、loss_val, macro_dice_val, micro_dice_val, perpix_acc_val, macro_iou_val, micro_iou_val
        self.epoch_result = {
            "epoch": list(range(1, self.epochs + 1)),
            "loss_tr": [],
            "loss_val": [],
            "macro_dice_val": [],
            "micro_dice_val": [],
            "perpix_acc_val": [],
            "macro_iou_val": [],
            "micro_iou_val": []
        }


    def DefineNetwork(self, net_name, loss_name):
        if net_name == 'Unet':
            self.net = model.UNet(n_channels=3, n_classes=1, bilinear=False)
        elif net_name == 'ResUnet':
            if self.Location:
                self.net = model.ResUNet(n_channels=3 + 2, n_classes=1, bilinear=False)
            else:
                self.net = model.ResUNet(n_channels=3, n_classes=1, bilinear=False)

        elif net_name == 'BCDUNet':
            from NewModels.BCDUnet.BCDUNet import BCDUNet
            self.net = BCDUNet(input_dim=3, output_dim=1)

        elif net_name == 'ResUnet_Location':
            self.net = model.ResUNet_Location(n_channels=3 + 2, n_classes=1, bilinear=False)
        elif net_name == 'ResUnet_SinusoidLocation':
            self.net = model.ResUNet_Location(n_channels=3, n_classes=1, bilinear=False)


        self.net.to(device=self.device)
        print('---------- Networks initialized -------------')
        total = sum(p.numel() for p in self.net.parameters())
       # for param in self.net.parameters():
         #     num_params += param.numel()
        print('[Network %s] Total number of parameters : %.3f M' % ('net', total / 1e6))
        print('-----------------------------------------------')
        # self.net = nn.DataParallel(self.net, device_ids=[0, 1, 2, 3])

        # detach all variables in teacher model
        self.loss_name = loss_name


        if loss_name == 'BCEloss':
            # self.criterion = loss.DiceCoeff()
            self.criterion = nn.BCEWithLogitsLoss()
        elif loss_name == 'Diceloss':
            self.criterion = Loss.DiceLoss(logit=True)
        elif loss_name == 'IoUloss':
            self.criterion = Loss.IoULoss(logit=True)
        elif loss_name == 'Dice+SupTopo_loss':
            self.criterion = Loss.DiceSupTopoLoss(logit=True, imgsize=self.masksize)
        elif loss_name == 'Dice+BCE_loss':
            self.criterion = Loss.DiceBCELoss(logit=True)
        elif loss_name == 'Dice+ConsistMSE_loss':
            self.criterion = Loss.Dice_ConsistMSELoss(logit=True)
        elif loss_name == 'Dice+ConsistDiscMSE_loss':
            self.criterion = Loss.Dice_ConsistMSELoss(logit=True)
        elif loss_name == 'Dice+ConsistSCL_loss':
            self.criterion = Loss.Dice_ConsistSCLLoss(logit=True, prior=self.mean_pos)
        elif loss_name == 'Dice+ConsistDice_loss':
            self.criterion = Loss.Dice_ConsistDiceLoss(logit=True)
        elif loss_name == 'Dice+ConsistMILMSE_loss':
            self.criterion = Loss.Dice_ConsistMILMSELoss(logit=True)
        elif loss_name == 'Dice+ConsistPriorMSE_loss':
            self.criterion = Loss.Dice_ConsistPriorMSELoss(logit=True, prior=self.mean_pos)
        elif loss_name == 'Dice+ConsistHingeMSE_loss':
            self.criterion = Loss.Dice_ConsistHingeMSELoss(logit=True, C=self.HingeC)
        elif loss_name == 'Dice+ConsistVar_loss':
            self.criterion = Loss.Dice_ConsistVarLoss(logit=True)
        elif loss_name == 'Dice+ConsistMSE+thin_loss':
            self.criterion = Loss.Dice_ConsistMSE_thin_Loss(logit=True)
        elif loss_name == 'Dice+ConsistL1_loss':
            self.criterion = Loss.Dice_ConsistL1Loss(logit=True)
        elif loss_name == 'Dice+ConsistLp_loss':
            self.criterion = Loss.Dice_ConsistLpLoss(lp=self.lp, logit=True)
        elif loss_name == 'Dice+ConsistDice_loss':
            self.criterion = Loss.Dice_ConsistDiceLoss(logit=True)
        elif loss_name == 'Dice+Contrastive_loss':
            self.criterion = Loss.Dice_Contrastive_Loss(logit=True)
        elif loss_name == 'Dice+CosineContrastive_loss':
            self.criterion = Loss.Dice_CosineContrastive_Loss(logit=True)
        elif loss_name == 'Dice+CosineContrastiveNoExp_loss':
            self.criterion = Loss.Dice_CosineContrastiveNoExp_Loss(logit=True)

        self.DiceLoss = Loss.DiceLoss(logit=True)
        try:
            self.TopoLoss = Loss.TopoLoss(size=[512, 512])
        except:
            self.TopoLoss = None
            pass

        self.MSELoss = Loss.MSELoss(logit=True)
        # self.JSDLoss = loss.JSDivLoss(logit=True)
        # self.FocalMSELoss = loss.FocalMSELoss(logit=True)


    def TrainOneEpoch_bk(self, writer=None, max_itr=np.inf):
        '''
        Train One Epoch for pi model
        :return:
        '''

        epoch_loss = 0.

        train_labeled_pred_all = []
        train_labeled_gt_all = []

        itr = 0

        while True:
            ## Get next batch train samples
            FinishEpoch, data = \
                self.Loader.NextTrainBatch()
            if FinishEpoch or itr > max_itr:
                break

            train_labeled_data = data['labeled']['data']
            train_labeled_gt = data['labeled']['gt']
            train_labeled_name = data['labeled']['name']
            train_unlabeled_data = data['unlabeled']['data']
            train_unlabeled_gt = data['unlabeled']['gt']
            train_unlabeled_name = data['unlabeled']['name']

            ## Apply Augmentation for both labeled and unlabeled data
            #   data ~ transformed image data, gt ~ transformed segmentation ground-truth, mask ~ mask for original frame
            #   Tform ~ transformation matrix
            train_labeled_data_view1, train_labeled_gt_view1, train_labeled_mask_view1, train_labeled_Tform_view1 = \
                self.ApplyAugmentation_Mask(train_labeled_data, train_labeled_gt)
            # train_labeled_data_view2, train_labeled_gt_view2, train_labeled_mask_view2, train_labeled_Tform_view2 = \
            #     self.ApplyAugmentation_Mask(train_labeled_data, train_labeled_gt)
            train_unlabeled_data_view1, train_unlabeled_gt_view1, train_unlabeled_mask_view1, train_unlabeled_Tform_view1 = \
                self.ApplyAugmentation_Mask(train_unlabeled_data, train_unlabeled_gt)
            # train_unlabeled_data_view2, train_unlabeled_gt_view2, train_unlabeled_mask_view2, train_unlabeled_Tform_view2 = \
            #     self.ApplyAugmentation_Mask(train_unlabeled_data, train_unlabeled_gt)



            ## train one iteration
            # move data to GPU
            train_labeled_data_view1 = torch.tensor(train_labeled_data_view1,device=self.device, dtype=torch.float32)
            # train_labeled_data_view2 = torch.tensor(train_labeled_data_view2,device=self.device, dtype=torch.float32)
            train_labeled_gt_view1 = torch.tensor(train_labeled_gt_view1,device=self.device, dtype=torch.float32)
            # train_labeled_gt_view2 = torch.tensor(train_labeled_gt_view2,device=self.device, dtype=torch.float32)
            train_unlabeled_data_view1 = torch.tensor(train_unlabeled_data_view1,device=self.device, dtype=torch.float32)
            # train_unlabeled_data_view2 = torch.tensor(train_unlabeled_data_view2,device=self.device, dtype=torch.float32)
            # train_unlabeled_gt_view1 = torch.tensor(train_unlabeled_gt_view1,device=self.device, dtype=torch.float32)
            # train_unlabeled_gt = torch.tensor(train_unlabeled_gt,device=self.device, dtype=torch.float32)

            ## forward pass for all views
            train_labeled_pred_view1 = self.net(train_labeled_data_view1)   # forward pass prediction of train labeled set view1
            # train_labeled_pred_view2 = self.net_ema(train_labeled_data_view2)   # forward pass prediction of train labeled set view2
            train_unlabeled_pred_view1 = self.net(train_unlabeled_data_view1)    # forward pass prediction of train unlabeled set view1
            # train_unlabeled_pred_view2 = self.net_ema(train_unlabeled_data_view2)   # forward pass prediction of train unlabeled set view2

            ## Adversarial attack to obtain view 2
            # sample random perturbation
            xi = 1e1
            eps = 1e0
            self.net.requires_grad = False
            r_labeled = xi * self._l2normalize(torch.randn(train_labeled_data_view1.shape,device=self.device))
            r_labeled.requires_grad = True
            train_labeled_data_view2 = train_labeled_data_view1 + r_labeled
            train_labeled_pred_view2 = self.net(train_labeled_data_view2)   # forward pass prediction of train labeled set view2
            r_unlabeled = xi * self._l2normalize(torch.randn(train_unlabeled_data_view1.shape,device=self.device))
            r_unlabeled.requires_grad = True
            train_unlabeled_data_view2 = train_unlabeled_data_view1 + r_unlabeled
            train_unlabeled_pred_view2 = self.net(train_unlabeled_data_view2)   # forward pass prediction of train unlabeled set view2

            # compute virtual consistency loss and adversarial gradient
            consist_loss = self.MSELoss(input1=torch.cat([train_labeled_pred_view1.detach(), train_unlabeled_pred_view1.detach()],dim=0),
                                        input2=torch.cat([train_labeled_pred_view2, train_unlabeled_pred_view2],dim=0))

            self.net.zero_grad()
            consist_loss.backward()
            d_labeled = self._l2normalize(r_labeled.grad)
            d_unlabeled = self._l2normalize(r_unlabeled.grad)

            # compute new losses with adversarial inputs
            self.net.requires_grad=True
            train_labeled_data_view2 = train_labeled_data_view1 + eps*d_labeled
            train_labeled_pred_view2 = self.net(
                train_labeled_data_view2)  # forward pass prediction of train labeled set view2
            train_unlabeled_data_view2 = train_unlabeled_data_view1 + eps*d_unlabeled
            train_unlabeled_pred_view2 = self.net(
                train_unlabeled_data_view2)  # forward pass prediction of train labeled set view2
            # consist_loss = self.MSELoss(train_labeled_pred_view1, train_labeled_pred_view2)
            consist_loss = self.MSELoss(
                input1=torch.cat([train_labeled_pred_view1.detach(), train_unlabeled_pred_view1.detach()], dim=0),
                input2=torch.cat([train_labeled_pred_view2, train_unlabeled_pred_view2], dim=0))

            ## inverse transform of predictions (tensors)
            # train_unlabeled_pred_view1_aligned = self.gt_model.invtransform_image_tensor(train_unlabeled_pred_view1, train_unlabeled_Tform_view1)
            # train_unlabeled_pred_view2_aligned = self.gt_model.invtransform_image_tensor(train_unlabeled_pred_view2, train_unlabeled_Tform_view2)
            # unlabeled_mask = torch.tensor(train_unlabeled_mask_view1 * train_unlabeled_mask_view2,dtype=torch.uint8,device=self.device)   # the overlap mask between all views
            # # select overlapped pixels
            # train_unlabeled_pred_view1_sel = torch.masked_select(train_unlabeled_pred_view1_aligned, unlabeled_mask)
            # train_unlabeled_pred_view2_sel = torch.masked_select(train_unlabeled_pred_view2_aligned, unlabeled_mask)
            # train_unlabeled_pred_allview_sel = torch.cat([train_unlabeled_pred_view1_sel,train_unlabeled_pred_view2_sel],dim=0)

            ## compute losses
            dice_loss = self.DiceLoss(train_labeled_pred_view1,train_labeled_gt_view1[:,None,...])

            loss = dice_loss + torch.tensor(self.W(epoch=float(self.epoch_cnt)),device=self.device)*consist_loss

            # loss = self.criterion(
            #     pred_labeled=torch.cat([train_labeled_pred_view1,train_labeled_pred_view2],dim=0),
            #     gt_labeled=torch.cat([train_labeled_gt_view1[:,None,...],train_labeled_gt_view2[:,None,...]],dim=0),
            #     pred_unlabeled=train_unlabeled_pred_allview_sel,
            #     weight=torch.tensor(self.W(epoch=float(self.epoch_cnt)),device=self.device))

            epoch_loss = epoch_loss * itr/(itr+1) + float(loss.item())/(itr+1)

            # accumulate predictions and ground-truths
            train_labeled_pred_all.append(train_labeled_pred_view1.detach().cpu().numpy())
            train_labeled_gt_all.append(train_labeled_gt_view1.detach().cpu().numpy())

            # del train_labeled_pred, train_labeled_gt
            # torch.cuda.empty_cache()
            with torch.cuda.device(self.device):
                torch.cuda.empty_cache()

            # backward propagation
            self.optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_value_(self.net.parameters(), 0.1)
            self.optimizer.step()

            # update global and local train steps
            self.global_step += 1
            itr += 1

        ## Evaluate current epoch performance
        train_labeled_pred_all = np.concatenate(train_labeled_pred_all)
        train_labeled_pred_all = np.squeeze(train_labeled_pred_all>0,axis=1).astype(float)  # binarize predictions
        train_labeled_gt_all = np.concatenate(train_labeled_gt_all).astype(float)
        perpix_acc = self.evaluator.perpixel_acc(train_labeled_pred_all, train_labeled_gt_all)  # evaluate per pixel accuracy
        persamp_iou = self.evaluator.persamp_iou(train_labeled_pred_all, train_labeled_gt_all)  # evaluate per sample iou
        micro_iou = self.evaluator.micro_iou(train_labeled_pred_all, train_labeled_gt_all)  # evaluate per sample iou

        self.tr_loss = epoch_loss
        self.tr_Acc = perpix_acc
        self.tr_macro_IoU = persamp_iou
        self.tr_micro_IoU = micro_iou

        self.epoch_cnt += 1 # increase epoch counter by 1

        ## Decay LearningRate
        self.lr_scheduler.step()

        return epoch_loss, perpix_acc, persamp_iou, micro_iou


    def TrainOneEpoch(self, writer=None, max_itr=np.inf, epoch=0):
        '''
        Train One Epoch for pi model
        :return:
        '''
        epoch_loss = 0.

        train_labeled_pred_all = []
        train_labeled_gt_all = []

        # enable network for training
        self.net.train()

        itr = 0

        while True:
            ## Get next batch train samples
            FinishEpoch, data = \
                self.Loader.NextTrainBatch(epoch)
            if FinishEpoch or itr > max_itr:
                break

            self.optimizer.zero_grad()

            train_labeled_data = data['labeled']['data']
            train_labeled_gt = data['labeled']['gt']
            train_labeled_name = data['labeled']['name']
            train_unlabeled_data = data['unlabeled']['data']
            train_unlabeled_gt = data['unlabeled']['gt']
            train_unlabeled_name = data['unlabeled']['name']

            ## Apply Augmentation for both labeled and unlabeled data
            #   data ~ transformed image data, gt ~ transformed segmentation ground-truth, mask ~ mask for original frame
            #   Tform ~ transformation matrix
            # train_labeled_data_view1, train_labeled_gt_view1, train_labeled_mask_view1, train_labeled_Tform_view1 = \
            #     self.ApplyAugmentation_Mask(train_labeled_data, train_labeled_gt)
            # train_labeled_data_view2, train_labeled_gt_view2, train_labeled_mask_view2, train_labeled_Tform_view2 = \
            #     self.ApplyAugmentation_Mask(train_labeled_data, train_labeled_gt)
            # train_unlabeled_data_view1, train_unlabeled_gt_view1, train_unlabeled_mask_view1, train_unlabeled_Tform_view1 = \
            #     self.ApplyAugmentation_Mask(train_unlabeled_data, train_unlabeled_gt)
            # train_unlabeled_data_view2, train_unlabeled_gt_view2, train_unlabeled_mask_view2, train_unlabeled_Tform_view2 = \
            #     self.ApplyAugmentation_Mask(train_unlabeled_data, train_unlabeled_gt)
            train_labeled_data_view1 = train_labeled_data.transpose([0,3,1,2])
            train_labeled_gt_view1 = train_labeled_gt
            train_unlabeled_data_view1 = train_unlabeled_data.transpose([0,3,1,2])

            ## train one iteration
            # move data to GPU
            train_labeled_data_view1 = torch.tensor(train_labeled_data_view1,device=self.device, dtype=torch.float32)
            train_labeled_gt_view1 = torch.tensor(train_labeled_gt_view1,device=self.device, dtype=torch.float32)
            train_unlabeled_data_view1 = torch.tensor(train_unlabeled_data_view1,device=self.device, dtype=torch.float32)


            ## forward pass for all views
            train_labeled_pred_view1 = self.net(train_labeled_data_view1)   # forward pass prediction of train labeled set view1
            train_unlabeled_pred_view1 = self.net(train_unlabeled_data_view1)    # forward pass prediction of train unlabeled set view1

            ## Adversarial attack to obtain view 2
            # sample random perturbation
            xi = 1e1
            eps = 1e0
            self.net.requires_grad = False
            r_labeled = xi * self._l2normalize(torch.randn(train_labeled_data_view1.shape,device=self.device))
            r_labeled.requires_grad = True
            train_labeled_data_view2 = train_labeled_data_view1 + r_labeled
            train_labeled_pred_view2 = self.net(train_labeled_data_view2)   # forward pass prediction of train labeled set view2
            r_unlabeled = xi * self._l2normalize(torch.randn(train_unlabeled_data_view1.shape,device=self.device))
            r_unlabeled.requires_grad = True
            train_unlabeled_data_view2 = train_unlabeled_data_view1 + r_unlabeled
            train_unlabeled_pred_view2 = self.net(train_unlabeled_data_view2)   # forward pass prediction of train unlabeled set view2

            # compute virtual consistency loss and adversarial gradient
            consist_loss = self.MSELoss(input1=torch.cat([train_labeled_pred_view1.detach(), train_unlabeled_pred_view1.detach()],dim=0),
                                        input2=torch.cat([train_labeled_pred_view2, train_unlabeled_pred_view2],dim=0))

            self.net.zero_grad()
            consist_loss.backward()
            d_labeled = self._l2normalize(r_labeled.grad)
            d_unlabeled = self._l2normalize(r_unlabeled.grad)

            # compute new losses with adversarial inputs
            self.net.requires_grad=True
            train_labeled_data_view2 = train_labeled_data_view1 + eps*d_labeled
            train_labeled_pred_view2 = self.net(
                train_labeled_data_view2)  # forward pass prediction of train labeled set view2
            train_unlabeled_data_view2 = train_unlabeled_data_view1 + eps*d_unlabeled
            train_unlabeled_pred_view2 = self.net(
                train_unlabeled_data_view2)  # forward pass prediction of train labeled set view2
            # consist_loss = self.MSELoss(train_labeled_pred_view1, train_labeled_pred_view2)
            consist_loss = self.MSELoss(
                input1=torch.cat([train_labeled_pred_view1.detach(), train_unlabeled_pred_view1.detach()], dim=0),
                input2=torch.cat([train_labeled_pred_view2, train_unlabeled_pred_view2], dim=0))

            ## compute losses
            dice_loss = self.DiceLoss(train_labeled_pred_view1,train_labeled_gt_view1[:,None,...])

            loss = dice_loss + torch.tensor(self.W(epoch=float(self.epoch_cnt)),device=self.device)*consist_loss


            epoch_loss = epoch_loss * itr/(itr+1) + float(loss.item())/(itr+1)

            # accumulate predictions and ground-truths
            train_labeled_pred_all.append(train_labeled_pred_view1.detach().cpu().numpy())
            train_labeled_gt_all.append(train_labeled_gt_view1.detach().cpu().numpy())

            # del train_labeled_pred, train_labeled_gt
            # torch.cuda.empty_cache()
            with torch.cuda.device(self.device):
                torch.cuda.empty_cache()

            # backward propagation
            self.optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_value_(self.net.parameters(), 0.1)
            self.optimizer.step()


            # print batch
            print('\rFinished {}-th epoch {}-th batch'.format(self.epoch_cnt, itr), end='')

            # update global and local train steps
            self.global_step += 1
            itr += 1

        self.tr_loss = epoch_loss
        self.epoch_result["loss_tr"].append(epoch_loss)

        self.epoch_cnt += 1 # increase epoch counter by 1

        ## Decay LearningRate
        self.lr_scheduler.step()

        return epoch_loss


    def ValOneEpoch(self, epoch=0):
        '''
        Evaluate one epoch on validation set
        :return:
        '''
        epoch_loss = 0.

        val_pred_all = []
        val_gt_all = []

        # enable network for evaluation
        self.net.eval()

        itr = 0

        while True:
            ## Get next batch val samples
            FinishEpoch, data = \
                self.Loader.NextValBatch(epoch)
            if FinishEpoch:
                break

            ## Apply Normalization
            val_data = self.ApplyNormalization(data['data'])

            val_data = np.transpose(val_data, [0, 3, 1, 2])
            val_gt = np.transpose(data['gt'], [0, 1, 2])

            ## val current batch
            val_data = torch.tensor(val_data, device=self.device, dtype=torch.float32)
            val_gt = torch.tensor(val_gt, device=self.device, dtype=torch.float32)

            # forward pass
            val_pred = self.net(val_data)  # forward pass prediction of train labeled set
            loss = self.DiceLoss(pred=val_pred[:, 0, ...], gt=val_gt)
            epoch_loss = epoch_loss*itr/(itr+1) + loss.item()/(itr+1)

            # accumulate predictions and ground-truths
            val_pred_all.append(val_pred.detach().cpu().numpy())
            val_gt_all.append(val_gt.detach().cpu().numpy())

            del val_pred, val_gt
            with torch.cuda.device(self.device):
                torch.cuda.empty_cache()

            itr += 1

        ## Evaluate val performance
        val_pred_all = np.concatenate(val_pred_all)
        val_pred_all = np.squeeze(val_pred_all > 0.5, axis=1).astype(float)  # binarize predictions
        val_gt_all = np.concatenate(val_gt_all).astype(float)

        perpix_acc = self.evaluator.perpixel_acc(val_pred_all, val_gt_all)  # evaluate per pixel accuracy
        persamp_iou = self.evaluator.persamp_iou(val_pred_all, val_gt_all)  # evaluate per sample iou
        micro_iou = self.evaluator.micro_iou(val_pred_all, val_gt_all)  # evaluate micro-average iou
        persamp_dice = self.evaluator.persamp_dice(val_pred_all, val_gt_all)  # persamp_dice
        micro_dice = self.evaluator.micro_dice(val_pred_all, val_gt_all)  # micro_dice

        self.val_loss = epoch_loss
        self.val_Acc = perpix_acc
        self.val_macro_IoU = persamp_iou
        self.val_micro_IoU = micro_iou
        self.val_macro_Dice = persamp_dice
        self.val_micro_Dice = micro_dice

        self.epoch_result["loss_val"].append(epoch_loss)
        self.epoch_result["macro_dice_val"].append(100 * np.mean(persamp_dice))
        self.epoch_result["micro_dice_val"].append(100 * micro_dice)
        self.epoch_result["perpix_acc_val"].append(100 * perpix_acc)
        self.epoch_result["macro_iou_val"].append(100 * np.mean(persamp_iou))
        self.epoch_result["micro_iou_val"].append(100 * micro_iou)

        return epoch_loss, persamp_dice, micro_dice, perpix_acc, persamp_iou, micro_iou


    def TestAll_SavePred(self,exp_fig=False,best_ckpt_filepath=None):
        '''
        Test all samples in the test set and export predictions
        :return:
        '''
        epoch_loss = 0.

        test_pred_all = []
        test_gt_all = []
        test_gt_org_all = []

        ## Restore best ckpt
        if best_ckpt_filepath is not None:
            self.net.load_state_dict(torch.load(best_ckpt_filepath,map_location=self.device))

        self.net.eval()

        itr = 0

        while True:
            ## Get next batch test samples
            FinishEpoch, data = \
                self.Loader.NextTestBatch()
            if FinishEpoch:
                break

            test_data = data['data']
            test_gt = data['gt']
            test_gt_org = data['gt_org']
            # test_gt_thin = data['gt_thin']
            test_names = data['name']

            ## Apply Normalization
            test_data = self.ApplyNormalization(test_data)

            test_data = np.transpose(test_data, [0, 3, 1, 2])
            test_gt = np.transpose(test_gt, [0, 1, 2])

            ## test current batch
            test_data = torch.tensor(test_data, device=self.device, dtype=torch.float32)
            test_gt = torch.tensor(test_gt, device=self.device, dtype=torch.float32)

            ## forward pass
            if self.Location:
                x, y = np.meshgrid(np.arange(0, test_data.shape[3]),
                                   np.arange(0, test_data.shape[2]))
                x = x[np.newaxis, np.newaxis, ...].astype(np.float32)
                y = y[np.newaxis, np.newaxis, ...].astype(np.float32)
                x = torch.tensor(np.tile(x, [test_data.shape[0], 1, 1, 1]),
                                 device=test_data.device)
                y = torch.tensor(np.tile(y, [test_data.shape[0], 1, 1, 1]),
                                 device=test_data.device)
                test_data = torch.cat([test_data, x, y], dim=1)
            t0 = time()
            test_pred = self.net(test_data)
            print('Time is =============',time()-t0)
            # losses = self.criterion(pred_labeled=test_pred[:, 0, ...], gt_labeled=test_gt)
            loss_class = self.DiceLoss(pred=test_pred[:, 0, ...],gt=test_gt)
            epoch_loss = epoch_loss*itr/(itr+1) + loss_class.detach().cpu().numpy()/(itr+1)

            # accumulate predictions and ground-truths
            test_pred = torch.sigmoid(test_pred)
            for pred_i in test_pred.detach().cpu().numpy():
                test_pred_all.append(pred_i[0])
            for gt_i in test_gt.detach().cpu().numpy():
                test_gt_all.append(gt_i)
            # test_pred_all.append(test_pred.detach().cpu().numpy())
            # test_gt_all.append(test_gt.detach().cpu().numpy())
            if test_gt_org is not None:
                for gt_i in test_gt_org:
                    test_gt_org_all.append(gt_i)

            # test_pred_all.append(test_pred.detach().cpu().numpy())
            # test_gt_all.append(test_gt.detach().cpu().numpy())

            # export prediction and gt figures
            if exp_fig:
                for img_i, gt_i, pred_i in zip(test_names, test_gt, test_pred):
                    exp_gt_filepath = os.path.join(self.export_path, 'gt', '{}_gt.png'.format(img_i))
                    pred_path = os.path.join(self.export_path, 'pred')
                    if not os.path.exists(pred_path):
                        os.makedirs(pred_path)
                    # plt.imsave(exp_gt_filepath,gt_i.detach().cpu().numpy())
                    # plt.imsave(exp_pred_filepath,pred_i.detach().cpu().numpy()[0])
                    ## Save Posterior
                    exp_pred_filepath = os.path.join(pred_path, '{}_pred.png'.format(img_i))
                    img = Image.fromarray(255 * pred_i.detach().cpu().numpy()[0]).convert('RGB')
                    img.save(exp_pred_filepath)
                    ## Save Binarized
                    exp_pred_filepath = os.path.join(pred_path, '{}_pred_bin.png'.format(img_i))
                    img = Image.fromarray(255. * (pred_i.detach().cpu().numpy()[0] > 0.5)).convert('RGB')
                    img.save(exp_pred_filepath)

            # increase local iteration
            itr += 1

        ## Evaluate test performance
        if self.target_data == 'CrackForest' or self.target_data == 'MITRoad' or \
                self.target_data == 'MITRoadClean' or self.target_data == 'Gaps384' or \
                ('EM' in self.target_data) or ('DRIVE' in self.target_data) or ('CHASEDB1' in self.target_data) or (
                'STARE' in self.target_data) or self.target_data == 'CORN1':
            test_pred_all = np.array(test_pred_all)
            test_pred_bin_all = (test_pred_all > 0.5).astype(float)  # binarize predictions
            test_gt_all = np.array(test_gt_all).astype(float)

            perpix_acc = self.evaluator.perpixel_acc(test_pred_bin_all, test_gt_all)  # etestuate per pixel accuracy
            persamp_iou = self.evaluator.persamp_iou(test_pred_bin_all, test_gt_all)  # evaluate per sample iou
            micro_iou = self.evaluator.micro_iou(test_pred_bin_all, test_gt_all)  # evaluate micro-average iou
            AIU = self.evaluator.AIU(test_pred_all, test_gt_all)  # evaluate AIU
            micro_F1, macro_F1 = self.evaluator.F1(test_pred_bin_all, test_gt_all)
            persamp_dice = self.evaluator.persamp_dice(test_pred_bin_all, test_gt_all)
            micro_dice = self.evaluator.micro_dice(test_pred_bin_all, test_gt_all)

        elif self.target_data == 'Crack500':
            perpix_acc, persamp_iou, micro_iou, AIU, micro_F1, macro_F1, macro_Precision, macro_Recall = \
                self.CalMetric_Crack500(test_pred_all, test_gt_org_all)

        self.best_te_loss = epoch_loss
        self.best_te_Acc = perpix_acc
        self.best_te_macro_IoU = persamp_iou
        self.best_te_micro_IoU = micro_iou
        self.best_te_AIU = AIU
        self.best_te_micro_F1 = micro_F1
        self.best_te_macro_F1 = macro_F1

        self.best_te_macro_Dice = persamp_dice
        self.best_te_micro_Dice = micro_dice

        return epoch_loss, persamp_dice, micro_dice, perpix_acc, persamp_iou, micro_iou, AIU


    def ApplyAugmentation_Mask(self, data, gt):
        '''
        Apply augmentation to batch data and obtain the valid region mask
        :return:
        '''

        ## Apply Augmentatoin
        # image level augmentation
        # data, gt = self.augmentor.augment(images=data.astype(np.float32), masks=gt.astype(np.float32))

        # geometric transformation augmentation
        self.gt_model.construct_random_transform(data)
        Tform = self.gt_model.Tform # transformation matrices    
        data = self.gt_model.transform_images(data, extrapolation='reflect')    # transformed image data
        gt = self.gt_model.transform_images(gt[..., np.newaxis], extrapolation='reflect')[..., 0]   # transformed ground-truth masks
        mask = np.ones_like(gt)
        mask = self.gt_model.transform_images(mask[..., np.newaxis], extrapolation='constant')[..., 0]
        mask = self.gt_model.invtransform_images(mask[..., np.newaxis], extrapolation='constant')[..., 0]   # valid mask in original frame

        ## Apply Normalization
        data = (data - self.Loader.mean)/self.Loader.stddev

        ## new dimension order
        data = np.transpose(data, [0, 3, 1, 2])
        gt = np.transpose(gt, [0, 1, 2])
        mask = np.transpose(mask, [0, 1, 2])

        return data, gt, mask, Tform


    class WeightRampup(nn.Module):
        '''
        Weight Rampup class
        :return:
        '''

        def __init__(self,RampupType='Exp',RampupEpoch=50):
            '''

            :param RampupType: Exp(Exponential), Step(Step increase)
            :param RampupEpoch: A rampup epoch constant
            '''
            super().__init__()
            self.RampupType = RampupType
            self.RampupEpoch = RampupEpoch

        def forward(self, **kwargs):

            epoch = kwargs['epoch']

            if self.RampupType == 'Exp':
                # return np.exp(-10. * (1 - np.clip(epoch, 0.0, self.RampupEpoch) / self.RampupEpoch) ** 2)
                return np.exp(-5.*(1-epoch/self.RampupEpoch)**2)
            elif self.RampupType == 'Step':
                return 1.0 if epoch >= self.RampupEpoch else 0.0

    def _l2normalize(self, input):
        '''
        l2 normalize torch tensor in the last dimension
        :return:
        '''

        return input/torch.sqrt(torch.sum(input**2,dim=(1,2,3),keepdim=True))


    def UpdateLatestModel(self):
        todelete_ckpt = os.path.join(self.ckpt_path,
                                     'model_epoch-{}.pt'.format(self.epoch_cnt - self.ValFreq * self.MaxKeepCkpt))
        if os.path.exists(todelete_ckpt):
            os.remove(todelete_ckpt)

        current_ckpt = os.path.join(self.ckpt_path, 'model_epoch-{}.pt'.format(self.epoch_cnt))
        torch.save(self.net.state_dict(), current_ckpt)

        if self.best_val_Dice < self.val_micro_Dice:
            self.best_val_Dice = self.val_micro_Dice
            best_ckpt = os.path.join(self.ckpt_path, 'model_epoch-{}.pt'.format('best'))
            os.system('cp {} {}'.format(current_ckpt, best_ckpt))

            self.UpdateBest()
            print('【train_unet_MT】 saved current epoch as the best up-to-date model')

    def ExportTensorboard(self):
        self.writer.add_scalar('loss/train', self.tr_loss, self.epoch_cnt)
        self.writer.add_scalar('loss/val', self.val_loss, self.epoch_cnt)
        self.writer.add_scalar('macro average Dice/val', np.mean(self.val_macro_Dice), self.epoch_cnt)
        self.writer.add_scalar('micro average Dice/val', np.mean(self.val_micro_Dice), self.epoch_cnt)
        self.writer.add_scalar('perpix_accuracy/val', 100 * self.val_Acc, self.epoch_cnt)
        self.writer.add_scalar('macro average IoU/val', np.mean(self.val_macro_IoU), self.epoch_cnt)
        self.writer.add_scalar('micro average IoU/val', np.mean(self.val_micro_IoU), self.epoch_cnt)


    def PrintTrValInfo(self):
        '''
        Print train and validation set information
        :return:
        '''
        print("【train_unet_MT】 ======================================================")
        print('Epoch: {}'.format(self.epoch_cnt))
        print('【train_unet_MT】 macro average Dice/val:{:.2f}%'.format(100 * np.mean(self.val_macro_Dice)))
        print('【train_unet_MT】 micro average Dice/val:{:.2f}%'.format(100 * self.val_micro_Dice))
        print('perpix_accuracy/val: {:.2f}%'.format(100 * self.val_Acc))
        print('macro average IoU/val:{:.2f}%'.format(100 * np.mean(self.val_macro_IoU)))
        print('micro average IoU/val:{:.2f}%'.format(100 * self.val_micro_IoU))
        print("【train_unet_MT】 ======================================================")



    def SaveAllSettings(self, args):
        '''
        Save All settings
        :param args:
        :return:
        '''

        if args.SaveRslt:

            self.settings_filepath = os.path.join(self.result_path,'settings.txt')

            with open(self.settings_filepath,'w') as fid:
                # fid.write('Host:{}\n'.format(socket.gethostname()))
                fid.write('GPU:{}\n'.format(args.GPU))
                fid.write('Network:{}\n'.format(args.net))
                fid.write('LearningRate:{}\n'.format(args.LearningRate))
                fid.write('Epoch:{}\n'.format(args.Epoch))
                fid.write('batchsize:{}\n'.format(args.batchsize))
                fid.write('labelpercent:{}\n'.format(args.labelpercent))
                fid.write('loss:{}\n'.format(args.loss))
                fid.write('HingeC:{}\n'.format(args.HingeC))
                fid.write('Temperature:{}\n'.format(args.Temperature))
                fid.write('lp:{}\n'.format(args.lp))
                fid.write('ssl:{}\n'.format(args.ssl))
                fid.write('EmaAlpha:{}\n'.format(self.alpha))
                fid.write('Gamma:{}\n'.format(args.Gamma))
                fid.write('RampupEpoch:{}\n'.format(args.RampupEpoch))
                fid.write('RampupType:{}\n'.format(args.RampupType))
                fid.write('Target Dataset:{}\n'.format(args.TargetData))
                fid.write('Aux Dataset:{}\n'.format(args.AddUnlab))
                fid.write('AddLocation:{}\n'.format(args.Location))

