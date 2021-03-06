N_GPU=2
WDIR='resnext101v12'
FOLD=0
SIZE='480'

for FOLD in  0 1 2
do  
    for HFLIP in F T
    do
        bsub  -q priority -gpu "num=$N_GPU:mode=exclusive_process" -app gpu -n =$N_GPU  -env LSB_CONTAINER_IMAGE=darraghdog/kaggle:apex_build \
            -m dbslp1827 -n 1 -R "span[ptile=4]" -o log_train_%J  sh -c "cd /share/dhanley2/rsna/scripts/$WDIR  && python3 trainorig.py  \
            --logmsg Rsna-lb-$SIZE-fp16 --start 0 --epochs 6 --fold $FOLD  --lr 0.00002 --batchsize 32  --workpath scripts/$WDIR  \
            --stage2 T --hflip $HFLIP --transpose F --infer EMB --imgpath data/mount/512X512X6/ --size $SIZE --weightsname weights/model_512_resnext101$FOLD.bin"
    done

    bsub  -q normal -gpu "num=$N_GPU:mode=exclusive_process" -app gpu -n =$N_GPU  -env LSB_CONTAINER_IMAGE=darraghdog/kaggle:apex_build \
            -m dbslp1827 -n 1 -R "span[ptile=4]" -o log_train_%J  sh -c "cd /share/dhanley2/rsna/scripts/$WDIR  && python3 trainorig.py  \
            --logmsg Rsna-lb-$SIZE-fp16 --start 0 --epochs 6 --fold $FOLD  --lr 0.00002 --batchsize 32  --workpath scripts/$WDIR  \
            --stage2 T --hflip F --transpose T --infer EMB --imgpath data/mount/512X512X6/ --size $SIZE --weightsname weights/model_512_resnext101$FOLD.bin"
done
