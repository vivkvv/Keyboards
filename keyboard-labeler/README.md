# keyboard-labeler

Desktop tool for keyboard photo segmentation, OCR recognition, and manual editing of key labels, icons, and dividers.

## What It Does

- segments keyboard keys from a photo using SAM
- runs recognition with EasyOCR and TrOCR
- keeps method-specific recognition candidates per key
- lets you edit text, icons, dividers, angle, size, and offsets
- saves and loads recognition state as JSON

## Requirements

- Windows
- Conda
- NVIDIA GPU
- CUDA 12.4-compatible PyTorch setup
- SAM checkpoint path provided through an environment variable

## Setup

```bash
conda env create -f environment.yml
conda activate keyboard-labeler
```

`requirements.txt` already includes the CUDA 12.4 PyTorch wheels.

## Model and Cache Locations

This project expects model locations to be configured through user-level environment variables.
A working Windows setup looks like this:

- `SAM_CHECKPOINT=D:\python_model_cache\sam\sam_vit_b.pth`
- `HF_HOME=D:\python_model_cache\huggingface`
- `HUGGINGFACE_HUB_CACHE=D:\python_model_cache\huggingface\hub`
- `TRANSFORMERS_CACHE=D:\python_model_cache\huggingface\hub`
- `HF_MODULES_CACHE=D:\python_model_cache\modules`
- `EASYOCR_MODULE_PATH=D:\python_model_cache\easyocr`
- `MODULE_PATH=D:\python_model_cache\easyocr`
- `TORCH_HOME=D:\python_model_cache\torch`
- `XDG_CACHE_HOME=D:\python_model_cache`

## SAM Checkpoint

Download:
- https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth

Expected location:
- `D:\python_model_cache\sam\sam_vit_b.pth`

## Run

```bash
python run_labeler.py
```

Optional image path:

```bash
python run_labeler.py assets\k860_1.png
```

## Repository Layout

- `run_labeler.py` - launcher
- `src/` - application code
- `ui/` - Qt `.ui` files
- `assets/` - sample source images
- `keyboards/` - saved recognition JSON files

## Notes

- generated recognition JSON files are ignored by git
- model weights and caches are not stored in the repository
- method-specific recognition candidates are preserved in Recognition JSON
