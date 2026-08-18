# agents/clusters.py
"""Which orchestrator owns which crews.

One fact, held nowhere else. `_CREW_AGENT_NAMES` says who runs in a crew, `CREW_DEPENDENCIES`
says what a crew waits on, and `CREW_CHARTER` says what can start it - but nothing said which
orchestrator a crew belongs to, because until now the question had one answer and no one had to
ask it. `pam` is the single agent in no crew, `ScopeNotice` explains her as an exception, and
every dispatch path she takes reaches the same nine crews.

That assumption breaks the moment there is a second orchestrator - a second PMO, or a coding
team whose crews are dispatched by a webhook rather than by a factory. Two agents would then be
in no crew, "the orchestrator" would name neither of them, and a picture drawn around a single
centre would have to be rewritten rather than extended. So the concept is modelled now, with one
cluster in it.

## What is declared here, and what is not

Only the cluster itself: its id, what to call it, which agent orchestrates it, and why it is a
cluster. **Its crews are not listed here.** A list of crew ids in this file would be an eleventh
restatement of the crew roll, which is precisely what `agents/graph.py` exists to end -
membership is declared once, on the crew, as `Charter.cluster`, and `graph.py` inverts it for
free exactly as it inverts `OUTPUT_OWNERS`.

Nor is the orchestrator's *authority* declared. Whether an orchestrator can actually start a
crew in its own cluster is derived in `agents/graph.py` from the tool it holds and the triggers
its crews declare - so `orchestrator` below is checked against the code rather than believed.
Declaring "pam owns these" while she held no dispatching tool would assemble a picture of a
pipeline nobody could start.

## What passes between clusters is derived, not declared

An edge between two crews is an information flow when the upstream crew writes an artefact the
downstream crew reads, and a sequencing dependency when it does not. That derivation is the
same whether the two crews are in one cluster or two, so an inter-cluster edge needs no
declaration of its own: it is an ordinary crew edge whose endpoints fall in different clusters.
`CrewEdge.crosses_clusters` in `agents/graph.py` is that comparison and nothing more. A second
cluster is therefore a data addition - one entry here, one `cluster=` on each of its crews - and
the edges between the two appear without anything else being written.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cluster:
    """One orchestrator and the crews it owns.

    `orchestrator` is an agent id, and it is an agent that runs in none of the cluster's own
    crews: it dispatches them rather than working inside them. `agents/graph.py` refuses an
    orchestrator that appears on its own ring, because a centre that is also a point on the
    circle is a picture that cannot be drawn and a model that cannot be read.

    `note` is prose because nothing derives it. It says what the cluster is on an engagement,
    which `pmo` does not, and it is written for the reader of the privacy page.
    """

    cluster_id: str
    label: str
    orchestrator: str
    note: str


# Keyed on the cluster id, which is permanent in the way every other id in this graph is: a
# crew's `Charter.cluster` cites it, and a cluster renamed rather than re-labelled would orphan
# every crew that named it.
CLUSTERS: dict[str, Cluster] = {
    "pmo": Cluster(
        cluster_id="pmo",
        label="Consulting PMO",
        orchestrator="pam",
        note=(
            "The consulting pipeline: one orchestrator, and the crews that take an engagement "
            "from the client's own documents to the business plan a board reads. It is the only "
            "cluster today, which is why the orchestrator has so far been describable as an "
            "exception - the one agent in no crew - rather than as the centre of something"
        ),
    ),
}
