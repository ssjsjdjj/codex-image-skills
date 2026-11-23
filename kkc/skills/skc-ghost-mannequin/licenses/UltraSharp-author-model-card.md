---
license: cc-by-nc-sa-4.0
pipeline_tag: image-to-image
tags:
- pytorch
- super-resolution
---
**Name:** 4x-UltraSharp (config and presets included!)

**License:** CC BY-NC-SA 4.0

**Link:** <https://mega.nz/folder/qZRBmaIY#nIG8KyWFcGNTuMX_XNbJ_g>

**Model Architecture:** ESRGAN

**Scale:** 4

**Purpose:** Any, it's universal. This model performs best on JPEG compressed images.


**Iterations:** 150k

**batch_size:** 4-8

**HR_size:** 128

**Epoch:** ~480

**Dataset:** So many. I used: RAW images shot by myself, SignatureEdits, AdobeMIT-5K, DIV2K, TLOK from brucethemoose, some rock/stone images from ALSA, and many images provided by @esrgan (thanks!)

**Dataset_size:** uh, ignore this. anywhere between 2k and 8k full size images throughout training

**OTF Training** Yes (custom augmentation presets)

**Pretrained_Model_G:** 4x-UniScale-Balanced


**Description:** This is my best model yet! It generates lots and lots of detail and leaves a nice texture on images. It works on most images, whether compressed or not. It does work best on JPEG compression though, as that's mostly what it was trained on. It has the ability to restore highly compressed images as well!

The model was trained with KernelGAN (thanks musl for supplying the blur kernels), noise patches, custom augmentation presets (are in with the model), and the losses: pixel, feature, cx, ssim, lpips, and fft. Mixup was used for a while, but abandedoned due to stability issues.

Gradient Clipping helped immensely with model stability throughout training.

Big thanks to musl for giving advice on how to further improve the model!