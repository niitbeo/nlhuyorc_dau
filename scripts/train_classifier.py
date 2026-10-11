import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset
from torchvision import datasets, transforms, models
import os
import time

def main():
    data_dir = 'classifier_data'
    batch_size = 32
    num_epochs = 5
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    
    # Image transformations
    # Images in VietOCR are height 32, so we scale them slightly
    data_transforms = {
        'train': transforms.Compose([
            transforms.Resize((64, 256)),
            transforms.RandomHorizontalFlip(p=0.5), # Address might be flipped
            transforms.ColorJitter(brightness=0.2, contrast=0.2),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ]),
        'val': transforms.Compose([
            transforms.Resize((64, 256)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ]),
    }
    
    # Since we didn't split into train/val folders, we'll load from the main folder and split programmatically
    full_dataset = datasets.ImageFolder(data_dir, transform=data_transforms['train'])
    
    train_size = int(0.8 * len(full_dataset))
    val_size = len(full_dataset) - train_size
    
    # Split
    train_dataset, val_dataset = torch.utils.data.random_split(full_dataset, [train_size, val_size])
    # Override val dataset transforms
    val_dataset.dataset.transform = data_transforms['val']
    
    dataloaders = {
        'train': DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=0),
        'val': DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    }
    
    dataset_sizes = {'train': train_size, 'val': val_size}
    class_names = full_dataset.classes
    print(f"Classes: {class_names}")
    
    # Load a lightweight ResNet18
    model = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
    
    # Freeze early layers
    for param in model.parameters():
        param.requires_grad = False
        
    # Replace final fully connected layer (binary classification: printed vs handwritten)
    num_ftrs = model.fc.in_features
    model.fc = nn.Linear(num_ftrs, len(class_names))
    
    model = model.to(device)
    
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.fc.parameters(), lr=0.001)
    
    best_acc = 0.0
    
    print("Starting training...")
    for epoch in range(num_epochs):
        print(f'Epoch {epoch+1}/{num_epochs}')
        print('-' * 10)
        
        for phase in ['train', 'val']:
            if phase == 'train':
                model.train()
            else:
                model.eval()
                
            running_loss = 0.0
            running_corrects = 0
            
            for inputs, labels in dataloaders[phase]:
                inputs = inputs.to(device)
                labels = labels.to(device)
                
                optimizer.zero_grad()
                
                with torch.set_grad_enabled(phase == 'train'):
                    outputs = model(inputs)
                    _, preds = torch.max(outputs, 1)
                    loss = criterion(outputs, labels)
                    
                    if phase == 'train':
                        loss.backward()
                        optimizer.step()
                        
                running_loss += loss.item() * inputs.size(0)
                running_corrects += torch.sum(preds == labels.data)
                
            epoch_loss = running_loss / dataset_sizes[phase]
            epoch_acc = running_corrects.double() / dataset_sizes[phase]
            
            print(f'{phase.capitalize()} Loss: {epoch_loss:.4f} Acc: {epoch_acc:.4f}')
            
            if phase == 'val' and epoch_acc > best_acc:
                best_acc = epoch_acc
                os.makedirs('weights', exist_ok=True)
                torch.save(model.state_dict(), 'weights/text_classifier.pth')
                
        print()
        
    print(f'Best Val Acc: {best_acc:4f}')
    print("Saved best model to weights/text_classifier.pth")

if __name__ == '__main__':
    main()
