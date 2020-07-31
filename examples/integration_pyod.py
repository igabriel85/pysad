import pyod.models.iforest
from sklearn.utils import shuffle
from evaluation.metrics import AUROCMetric
from pysad.models.half_space_trees import HalfSpaceTrees
from pysad.models.reference_window_model import ReferenceWindowModel
from streaming.array_iterator import ArrayIterator
from utils.data import Data
from tqdm import tqdm

data = Data("data")

X_all, y_all = data.get_data("arrhythmia.mat")
X_all, y_all = shuffle(X_all, y_all)

model = ReferenceWindowModel(model_cls=pyod.models.iforest.IForest, window_size=240, sliding_size=30, initial_window_X=X_all[:100])

iterator = ArrayIterator(shuffle=False)

auroc = AUROCMetric()

y_pred = []
for X, y in tqdm(iterator.iter(X_all[100:], y_all[100:])):
    model.fit_partial(X)
    score = model.score_partial(X)

    y_pred.append(score)

    auroc.update(y, score)

print("AUROC: ", auroc.get())