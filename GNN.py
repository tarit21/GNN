
import argparse
import time
from tqdm import tqdm

import torch
import torch.nn.functional as F
from torch.utils.data import random_split
from torch_geometric.data import DataLoader
from torch.nn import Linear
from torch_geometric.nn import global_mean_pool, GATConv
from torch_geometric.datasets import TUDataset

from sklearn.metrics import f1_score, accuracy_score, recall_score, precision_score

parser = argparse.ArgumentParser()

# original model parameters
parser.add_argument('--seed', type=int, default=777, help='random seed')
parser.add_argument('--device', type=str, default='cuda:0', help='specify cuda devices')

# hyper-parameters
parser.add_argument('--dataset', type=str, default='PROTEINS', help='DD/PROTEINS/NCI1/NCI109/Mutagenicity/ENZYMES')
parser.add_argument('--batch_size', type=int, default=128, help='batch size')
parser.add_argument('--lr', type=float, default=0.001, help='learning rate')
parser.add_argument('--weight_decay', type=float, default=0.01, help='weight decay')
parser.add_argument('--nhid', type=int, default=128, help='hidden size')
parser.add_argument('--epochs', type=int, default=100, help='maximum number of epochs')

args = parser.parse_args()
torch.manual_seed(args.seed)
if torch.cuda.is_available():
	torch.cuda.manual_seed(args.seed)

dataset = TUDataset('data/', name=args.dataset, use_node_attr=True)

args.num_classes = dataset.num_classes
args.num_features = dataset.num_features

print(args)

num_training = int(len(dataset) * 0.6)
num_val = int(len(dataset) * 0.1)
num_test = len(dataset) - (num_training + num_val)
training_set, validation_set, test_set = random_split(dataset, [num_training, num_val, num_test])

train_loader = DataLoader(training_set, batch_size=args.batch_size, shuffle=True)
val_loader = DataLoader(validation_set, batch_size=args.batch_size, shuffle=False)
test_loader = DataLoader(test_set, batch_size=args.batch_size, shuffle=False)


class Net(torch.nn.Module):
	def __init__(self):
		super(Net, self).__init__()

		self.num_features = dataset.num_features
		self.nhid = args.nhid

		self.conv1 = GATConv(self.num_features, self.nhid * 2)
		self.conv2 = GATConv(self.nhid * 2, self.nhid * 2)

		self.fc1 = Linear(self.nhid * 2, self.nhid)
		self.fc2 = Linear(self.nhid, dataset.num_classes)

	def forward(self, x, edge_index, batch):

		x = F.selu(self.conv1(x, edge_index))
		x = F.selu(self.conv2(x, edge_index))
		x = F.selu(global_mean_pool(x, batch))
		x = F.selu(self.fc1(x))
		x = F.dropout(x, p=0.5, training=self.training)
		x = self.fc2(x)
		return F.log_softmax(x, dim=-1)


def eval(log):

	accuracy, f1_macro, precision, recall = 0, 0, 0, 0

	prob_log, label_log = [], []

	for batch in log:
		pred_y, y = batch[0].data.cpu().numpy().argmax(axis=1), batch[1].data.cpu().numpy().tolist()
		prob_log.extend(batch[0].data.cpu().numpy()[:, 1].tolist())
		label_log.extend(y)

		accuracy += accuracy_score(y, pred_y)
		f1_macro += f1_score(y, pred_y, average='macro')
		precision += precision_score(y, pred_y, zero_division=0)
		recall += recall_score(y, pred_y, zero_division=0)

	return accuracy/len(log), f1_macro/len(log), precision/len(log), recall/len(log)


def compute_test(loader):
	model.eval()
	loss_test = 0.0
	out_log = []
	with torch.no_grad():
		for data in loader:
			data = data.to(args.device)
			out = model(data.x, data.edge_index, data.batch)
			y = data.y
			out_log.append([F.softmax(out, dim=1), y])
			loss_test += F.nll_loss(out, y).item()
	return eval(out_log), loss_test


model = Net().to(args.device)
model = model.to(args.device)
optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)


if __name__ == '__main__':
	# Model training
	out_log = []

	t = time.time()
	model.train()
	for epoch in tqdm(range(args.epochs)):
		loss_train = 0.0
		correct = 0
		for i, data in enumerate(train_loader):
			optimizer.zero_grad()
			data = data.to(args.device)
			out = model(data.x, data.edge_index, data.batch)
			y = data.y
			loss = F.nll_loss(out, y)
			loss.backward()
			optimizer.step()
			loss_train += loss.item()
			out_log.append([F.softmax(out, dim=1), y])
		acc_train, _, _, recall_train = eval(out_log)
		[acc_val, _, _, recall_val], loss_val = compute_test(val_loader)
		print(f'loss_train: {loss_train:.4f}, acc_train: {acc_train:.4f},'
			  f' recall_train: {recall_train:.4f}, loss_val: {loss_val:.4f},'
			  f' acc_val: {acc_val:.4f}, recall_val: {recall_val:.4f}')

	[acc, f1_macro, precision, recall], test_loss = compute_test(test_loader)
	print(f'Test set results: acc: {acc:.4f}, f1_macro: {f1_macro:.4f}, '
		  f'precision: {precision:.4f}, recall: {recall:.4f}')
