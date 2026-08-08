"""Demonstrate FIX 1 (the autocorrelation flaw) on synthetic data.

If the flaw is real, then even on PURE RANDOM data with no regime structure
whatsoever, the overlapping-window matrix will show a high persistence
diagonal — because consecutive 20-day windows share 19 days of data, so the
label physically cannot change quickly. Stride sampling should collapse it
back toward the no-signal baseline.
"""
import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
N, WINDOW, THRESH = 6000, 20, 0.05

# Pure random walk: zero regime structure by construction.
rets = rng.normal(0, 0.01, N)
close = pd.Series(100 * np.exp(np.cumsum(rets)))


def label(c, window=WINDOW, thresh=THRESH):
    r = c.pct_change(window)
    lab = pd.Series(1, index=c.index, dtype=int)   # 1 = sideways
    lab[r > thresh] = 2                            # 2 = bull
    lab[r < -thresh] = 0                           # 0 = bear
    return lab.dropna()


def matrix(labels):
    counts = np.zeros((3, 3))
    a = labels.to_numpy()
    for i in range(len(a) - 1):
        counts[a[i], a[i + 1]] += 1
    rs = counts.sum(axis=1, keepdims=True)
    rs[rs == 0] = 1
    return counts / rs


labels = label(close)
overlapping = matrix(labels)                 # v1 behaviour: every day
strided = matrix(labels.iloc[::WINDOW])      # v2 fix: non-overlapping

names = ["Bear", "Side", "Bull"]
print("Synthetic PURE RANDOM WALK — there is no real regime persistence here.\n")
print("OVERLAPPING (v1, every day — 19 of 20 days shared):")
for i, n in enumerate(names):
    print(f"  {n}: " + "  ".join(f"{overlapping[i][j]:.3f}" for j in range(3)))
print(f"  -> persistence diagonal: {np.diag(overlapping).round(3)}")
print(f"  -> mean self-transition: {np.diag(overlapping).mean():.3f}")

print("\nSTRIDE-SAMPLED (v2, every 20th bar — non-overlapping):")
for i, n in enumerate(names):
    print(f"  {n}: " + "  ".join(f"{strided[i][j]:.3f}" for j in range(3)))
print(f"  -> persistence diagonal: {np.diag(strided).round(3)}")
print(f"  -> mean self-transition: {np.diag(strided).mean():.3f}")

print("\nVERDICT: any persistence in the overlapping matrix is a MEASUREMENT")
print("ARTIFACT of window overlap, not a property of the market.")
