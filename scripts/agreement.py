import argparse
from collections import OrderedDict
from pathlib import Path

from .score import (
    CORRECT_A,
    CORRECT_B,
    INCORRECT_A,
    MISSING_A,
    MISSING_B,
    PARTIAL_A,
    SPURIOUS_A,
    SPURIOUS_B,
    match_keyphrases,
    match_relations,
)
from .utils import Collection, DisjointSet


def partial_score(keyphrase1, keyphrase2):
    intersection, union = overlap_spans(keyphrase1.spans, keyphrase2.spans)
    return intersection / union


def overlap_spans(spans1, spans2):
    """
    >>> overlap_spans([ (2,8) ], [ (4,10) ])
    (4, 8)
    >>> overlap_spans([ (2,8) ], [ (8,10) ])
    (0, 8)
    >>> overlap_spans([ (2,8), (8,10) ], [ (8,10) ])
    (2, 8)
    >>> overlap_spans([ (2,8), (9,10) ], [ (8,10) ])
    (1, 8)
    """

    tags = [0, 0] * len(spans1) + [1, 1] * len(spans2)
    spans = [x for span in spans1 + spans2 for x in span]

    state = [False, False]
    last = 0
    union = 0
    intersection = 0

    for span, tag in sorted(zip(spans, tags)):
        delta = span - last
        if all(state):
            intersection += delta
        if any(state):
            union += delta
        last = span
        state[tag] ^= True  # same as: state[tag] = not state[tag]

    return intersection, union


def concepts_agreement(data, all=True):
    assert (
        all or not data[INCORRECT_A]
    ), "For a single concept class, no incorrect matches are allowed"

    c_score = len(data[CORRECT_A])
    p_score = sum(partial_score(a, b) for a, b in data[PARTIAL_A].items())
    n = sum(
        len(data[x]) for x in [CORRECT_A, PARTIAL_A, MISSING_A, SPURIOUS_A, INCORRECT_A]
    )
    # print(c_score, p_score, len(data[PARTIAL_A]), len(data[MISSING_A]), len(data[SPURIOUS_A]), len(data[INCORRECT_A]))
    return (c_score + p_score) / n


def relations_agreement(data):
    c_score = len(data[CORRECT_B])
    n = sum(len(data[x]) for x in [CORRECT_B, MISSING_B, SPURIOUS_B])
    # print(c_score, len(data[MISSING_B]), len(data[SPURIOUS_B]))
    return c_score / n if n else 1.0


def agreement(data):
    c_score = len(data[CORRECT_A]) + len(data[CORRECT_B])
    p_score = sum(partial_score(a, b) for a, b in data[PARTIAL_A].items())
    n = sum(len(ann) for ann in data.values())
    # print(c_score, p_score, len(data[PARTIAL_A]), len(data[MISSING_A]),
    #  len(data[SPURIOUS_A]), len(data[INCORRECT_A]),
    #  len(data[MISSING_B]), len(data[SPURIOUS_B]))
    return (c_score + p_score) / n


def compute_metrics(data):
    return {
        "concepts_agreement": concepts_agreement(data),
        "relations_agreement": relations_agreement(data),
        "agreement": agreement(data),
    }


def load_corpus(anns_path: Path, clean=True) -> Collection:
    collection = Collection()

    for file in sorted(anns_path.iterdir()):
        if file.name.endswith(".txt"):
            collection.load(file)

    if clean:
        for s in collection.sentences:
            overlaps = s.overlapping_keyphrases()

            if overlaps:
                print("Found overlapping:", overlaps)
                s.merge_overlapping_keyphrases()
                overlaps = s.overlapping_keyphrases()

            dups = s.dup_relations()

            if dups:
                print(
                    "Found duplicated relations %r in sentence '%s'"
                    % ([v[0] for v in dups.values()], s.text)
                )
                s.remove_dup_relations()
                dups = s.dup_relations()

            assert not overlaps
            assert not dups

    return collection


def coordinate(gold, submit):
    i = 0
    while i < min(len(gold), len(submit)):
        if gold.sentences[i].text == submit.sentences[i].text:
            i += 1
            continue
        if gold.sentences[i + 1].text == submit.sentences[i].text:
            print("Dropped:", gold.sentences[i].text)
            del gold.sentences[i]
        elif gold.sentences[i].text == submit.sentences[i + 1].text:
            print("Dropped:", submit.sentences[i].text)
            del submit.sentences[i]
        else:
            print("Dropped:", gold.sentences[i].text)
            print("Dropped:", submit.sentences[i].text)
            del gold.sentences[i]
            del submit.sentences[i]
    while len(gold) != min(len(gold), len(submit)):
        gold.pop()
    while len(submit) != min(len(gold), len(submit)):
        submit.pop()


def main(gold_dir: Path, submit_dir: Path, propagate_error=True):
    gold_collection = load_corpus(gold_dir)
    submit_collection = load_corpus(submit_dir)
    coordinate(gold_collection, submit_collection)

    keyphrases = sorted(
        set(x.label for s in gold_collection.sentences for x in s.keyphrases)
    )
    relations = sorted(
        set(x.label for s in gold_collection.sentences for x in s.relations)
    )

    history = {}

    for labels, select in zip(
        [keyphrases, relations, ["Global"]],
        [Collection.filter_keyphrase, Collection.filter_relation, lambda x, y: x],
    ):
        for label in labels:
            gold = select(gold_collection, [label, "same-as"])
            submit = select(submit_collection, [label, "same-as"])

            data = OrderedDict()

            dataA = match_keyphrases(gold, submit, skip_incorrect=True)
            data.update(dataA)

            dataB = match_relations(
                gold,
                submit,
                dataA,
                skip_same_as=(label != "same-as" and label in relations),
                propagate_error=propagate_error,
            )
            data.update(dataB)

            history[label] = data
            metrics = compute_metrics(data)

            for key, value in metrics.items():
                print(label, "{0}: {1:0.4}".format(key, value))

    return data, history


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("gold")
    parser.add_argument("submit")
    parser.add_argument("--isolate", action="store_false")
    args = parser.parse_args()
    main(Path(args.gold), Path(args.submit), args.isolate)
