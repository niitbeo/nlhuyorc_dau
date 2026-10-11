import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from vietocr.tool.config import Cfg
from vietocr.model.trainer import Trainer
import torch

def train_pro():
    config = Cfg.load_config_from_name('vgg_transformer')
    
    # Dataset combined
    config['dataset']['name'] = 'combined_handwriting'
    config['dataset']['data_root'] = ''  # Absolute paths are in the txt
    config['dataset']['train_annotation'] = r'd:\orc\train_combined.txt'
    config['dataset']['valid_annotation'] = r'd:\orc\val_combined.txt'
    
    # Use Printed Text weights (which has robust positional encoding for long sequences)
    config['pretrain'] = r'd:\orc\weights\transformerocr_finetuned.pth'
    
    config['dataset']['image_max_width'] = 2048
    config['dataset']['image_min_width'] = 32
    
    config['trainer']['batch_size'] = 4  # Giảm xuống 4 để tránh tràn 4GB VRAM khi ảnh dài 2048
    config['trainer']['iters'] = 10000  # Train for 10000 iterations for the massive dataset
    config['trainer']['print_every'] = 50
    config['trainer']['valid_every'] = 500
    config['trainer']['export'] = r'd:\orc\weights\handwriting_pro.pth'
    
    config['trainer']['checkpoint'] = r'd:\orc\checkpoint_hw_pro.pth'
    
    config['dataloader']['num_workers'] = 0
    config['device'] = 'cuda:0' if torch.cuda.is_available() else 'cpu'

    trainer = Trainer(config, pretrained=True) # Mấu chốt! pretrained=True thì nó mới nạp file weights vào.
    trainer.config.save('configs/hw_pro.yml')
    trainer.train()

if __name__ == '__main__':
    train_pro()
