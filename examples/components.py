"""Synthetic code for retrieval only. Not competition inference."""


def spectrum_similarity(query_peaks, reference_peaks):
    cosine = sum(a * b for a, b in zip(query_peaks, reference_peaks))
    return cosine


def rerank_candidates(candidates, spectrum_scores):
    return sorted(candidates, key=lambda c: spectrum_scores[c], reverse=True)


def generate_smiles(model, formula):
    return model.beam_decode(formula)
