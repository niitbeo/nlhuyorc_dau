import os
import yaml
from vietocr.tool.config import Cfg
from vietocr.model.trainer import Trainer
import argparse
import sys

def main(args):
    # Load base configuration
    config = Cfg.load_config_from_file('configs/vgg_transformer_base.yml')
    
    # Update for our local dataset
    config['dataset']['name'] = 'data'
    config['dataset']['data_root'] = 'data'
    config['dataset']['train_annotation'] = 'train/labels.txt'
    config['dataset']['valid_annotation'] = 'val/labels.txt'
    
    # We want to fine-tune the pretrained model
    config['pretrain'] = 'https://vocr.vn/data/vietocr/vgg_transformer.pth'
    
    # 1050 Ti constraints (4GB VRAM)
    config['trainer']['batch_size'] = args.batch_size
    config['trainer']['iters'] = args.iters
    config['trainer']['print_every'] = 50
    config['trainer']['valid_every'] = 500
    
    # Dataloader for Windows
    config['dataloader']['num_workers'] = 0  # 0 is safer on Windows
    
    # Optimizer settings for fine-tuning
    config['optimizer']['max_lr'] = 0.0001
    
    # Output directories
    os.makedirs('checkpoint', exist_ok=True)
    os.makedirs('weights', exist_ok=True)
    
    config['trainer']['checkpoint'] = './checkpoint/transformerocr_checkpoint.pth'
    config['trainer']['export'] = './weights/transformerocr_finetuned.pth'
    config['trainer']['log'] = './train.log'
    
    # Check if GPU is actually available
    import torch
    if not torch.cuda.is_available():
        print("WARNING: CUDA is not available. Training will be on CPU and very slow.")
        config['device'] = 'cpu'
    else:
        print(f"CUDA available. Using GPU: {torch.cuda.get_device_name(0)}")
        config['device'] = 'cuda:0'
        
    print(f"Starting training with batch_size={config['trainer']['batch_size']} for {config['trainer']['iters']} iterations.")
    
    trainer = Trainer(config, pretrained=True)
    trainer.config.save('configs/vgg_transformer_finetune.yml')
    
    # Start training
    trainer.train()
    
    print("Training finished! Weights exported to ./weights/transformerocr_finetuned.pth")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch_size', type=int, default=16, help='Batch size (default: 16 for 4GB VRAM)')
    parser.add_argument('--iters', type=int, default=5000, help='Number of iterations')
    args = parser.parse_args()
    
    main(args)
