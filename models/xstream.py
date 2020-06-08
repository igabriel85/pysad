import numpy as np

from models.base_model import BaseModel
from projection.streamhash_projector import StreamhashProjector


class xStream(BaseModel):

    """

    Reference: https://github.com/cmuxstream/cmuxstream-core
    """
    def __init__(self, n_components=100, n_chains=100, depth=25, window_size=25, **kwargs):
        super().__init__(**kwargs)

        self.streamhash = StreamhashProjector(n_components=n_components)
        deltamax = np.ones(n_components) * 0.5
        deltamax[np.abs(deltamax) <= 0.0001] = 1.0
        self.window_size = window_size
        self.hs_chains = HSChains(deltamax=deltamax, n_chains=n_chains, depth=depth)

        self.step = 0
        self.cur_window = []
        self.ref_window = None

    def fit_partial(self, X, y=None):
        self.step += 1

        X = self.streamhash.fit_transform_partial(X)

        X = X.reshape(1, -1)
        self.cur_window.append(X)

        self.hs_chains.fit(X)

        if self.step % self.window_size == 0:
            self.ref_window = self.cur_window
            self.cur_window = []
            deltamax = self._compute_deltamax()
            self.hs_chains.set_deltamax(deltamax)
            self.hs_chains.next_window()

        return self

    def score_partial(self, X):
        X = self.streamhash.fit_transform_partial(X)
        X = X.reshape(1, -1)
        score = self.hs_chains.score(X).flatten()

        return score

    def _compute_deltamax(self):
        mx = np.max(np.concatenate(self.ref_window, axis=0), axis=0)
        mn = np.min(np.concatenate(self.ref_window, axis=0), axis=0)

        deltamax = (mx - mn)/2.0
        deltamax[np.abs(deltamax) <= 0.0001] = 1.0

        return deltamax


class Chain:

    def __init__(self, deltamax, depth):
        k = len(deltamax)

        self.depth = depth
        self.fs = [np.random.randint(0, k) for d in range(depth)]
        self.cmsketches = [{} for i in range(depth)] * depth
        self.cmsketches_cur = [{} for i in range(depth)] * depth

        self.deltamax = deltamax # feature ranges
        self.rand_arr = np.random.rand(k)
        self.shift = self.rand_arr * deltamax

        self.is_first_window = True

    def fit(self, X):
        prebins = np.zeros(X.shape, dtype=np.float)
        depthcount = np.zeros(len(self.deltamax), dtype=np.int)
        for depth in range(self.depth):
            f = self.fs[depth]
            depthcount[f] += 1

            if depthcount[f] == 1:
                prebins[:,f] = (X[:,f] + self.shift[f])/self.deltamax[f]
            else:
                prebins[:,f] = 2.0*prebins[:,f] - self.shift[f]/self.deltamax[f]

            if self.is_first_window:
                cmsketch = self.cmsketches[depth]
                for prebin in prebins:
                    l = tuple(np.floor(prebin).astype(np.int))
                    if not l in cmsketch:
                        cmsketch[l] = 0
                    cmsketch[l] += 1

                self.cmsketches[depth] = cmsketch

                self.cmsketches_cur[depth] = cmsketch

            else:
                cmsketch = self.cmsketches_cur[depth]

                for prebin in prebins:
                    l = tuple(np.floor(prebin).astype(np.int))
                    if not l in cmsketch:
                        cmsketch[l] = 0
                    cmsketch[l] += 1

                self.cmsketches_cur[depth] = cmsketch

        return self

    def bincount(self, X):
        scores = np.zeros((X.shape[0], self.depth))
        prebins = np.zeros(X.shape, dtype=np.float)
        depthcount = np.zeros(len(self.deltamax), dtype=np.int)
        for depth in range(self.depth):
            f = self.fs[depth]
            depthcount[f] += 1

            if depthcount[f] == 1:
                prebins[:,f] = (X[:,f] + self.shift[f])/self.deltamax[f]
            else:
                prebins[:,f] = 2.0*prebins[:,f] - self.shift[f]/self.deltamax[f]

            cmsketch = self.cmsketches[depth]
            for i, prebin in enumerate(prebins):
                l = tuple(np.floor(prebin).astype(np.int))
                if not l in cmsketch:
                    scores[i,depth] = 0.0
                else:
                    scores[i,depth] = cmsketch[l]

        return scores

    def score(self, X):
        # scale score logarithmically to avoid overflow:
        #    score = min_d [ log2(bincount x 2^d) = log2(bincount) + d ]
        scores = self.bincount(X)
        depths = np.array([d for d in range(1, self.depth+1)])
        scores = np.log2(1.0 + scores) + depths # add 1 to avoid log(0)
        return -np.min(scores, axis=1)

    def next_window(self):
        self.is_first_window = False
        self.cmsketches = self.cmsketches_cur
        self.cmsketches_cur = [{} for _ in range(self.depth)] * self.depth


class HSChains:
    def __init__(self, deltamax, n_chains=100, depth=25):
        self.nchains = n_chains
        self.depth = depth
        self.chains = []

        for i in range(self.nchains):

            c = Chain(deltamax=deltamax, depth=self.depth)
            self.chains.append(c)

    def score(self, X):
        scores = np.zeros(X.shape[0])
        for ch in self.chains:
            scores += ch.score(X)

        scores /= float(self.nchains)
        return scores

    def fit(self, X):
        for ch in self.chains:
            ch.fit(X)

    def next_window(self):
        for ch in self.chains:
            ch.next_window()

    def set_deltamax(self, deltamax):
        for ch in self.chains:
            ch.deltamax = deltamax
            ch.shift = ch.rand_arr * deltamax