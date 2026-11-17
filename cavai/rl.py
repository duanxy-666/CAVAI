"""Research-only RL policy interface. Not used for production decisions until reviewed labels exist."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
import random

ALLOWED_LABEL_SOURCES = {"reviewed_benchmark", "qualified_engineer_review"}

@dataclass(frozen=True)
class InspectionState:
    cad_type: str
    risk_bucket: str
    remaining_budget_bucket: int
    checks_done: tuple[str,...]

    def key(self) -> tuple:
        return (self.cad_type,self.risk_bucket,self.remaining_budget_bucket,tuple(sorted(self.checks_done)))

@dataclass(frozen=True)
class ReviewedFeedback:
    label_source: str
    truth_is_complete: bool
    true_defect_ids: frozenset[str]
    correctly_detected_ids: frozenset[str]
    false_alarm_ids: frozenset[str]
    check_cost_units: float

    def __post_init__(self):
        if self.label_source not in ALLOWED_LABEL_SOURCES:
            raise ValueError("Unverified model/LLM guesses cannot be reward labels")
        if not self.truth_is_complete:
            raise ValueError("Complete ground truth required to score missed defects")
        if not self.correctly_detected_ids <= self.true_defect_ids:
            raise ValueError("Detected true defects must appear in reviewed ground truth")
        if self.false_alarm_ids & self.true_defect_ids:
            raise ValueError("False alarms cannot also be true defects")
        if self.check_cost_units < 0:
            raise ValueError("Non-negative check cost required")

def reward_from_review(feedback: ReviewedFeedback) -> tuple[float,dict]:
    """Reward is computed ONLY after reliable independent defect verification."""
    tp = len(feedback.correctly_detected_ids)
    fn = len(feedback.true_defect_ids-feedback.correctly_detected_ids)
    fp = len(feedback.false_alarm_ids)
    reward = 8.0*tp - 12.0*fn - 5.0*fp - 0.4*feedback.check_cost_units
    return reward,{"TP":tp,"FN":fn,"FP":fp,"cost":feedback.check_cost_units}

class TabularQPolicy:
    """Small discrete action-space demonstration; no claim of trained policy quality."""
    def __init__(self,alpha:float=.2,gamma:float=.9,epsilon:float=.1,seed:int=2026):
        if not (0 < alpha <= 1 and 0 <= gamma <= 1 and 0 <= epsilon <= 1):
            raise ValueError("Invalid alpha/gamma/epsilon")
        self.alpha,self.gamma,self.epsilon=alpha,gamma,epsilon
        self.table:dict[tuple,float]={}
        self.rng=random.Random(seed)

    def q(self,state:InspectionState,action:str)->float:
        return self.table.get((state.key(),action),0.)

    def choose(self,state:InspectionState,available:Iterable[str],explore:bool=False)->str:
        actions=sorted(set(available))
        if not actions:
            raise ValueError("No available CAD tools")
        if explore and self.rng.random() < self.epsilon:
            return self.rng.choice(actions)
        best=max(self.q(state,a) for a in actions)
        return next(a for a in actions if self.q(state,a)==best)

    def update(self,state:InspectionState,action:str,reward:float,
               next_state:InspectionState,next_actions:Iterable[str])->float:
        actions=list(next_actions)
        future=max((self.q(next_state,a) for a in actions),default=0.)
        previous=self.q(state,action)
        updated=previous+self.alpha*(reward+self.gamma*future-previous)
        self.table[(state.key(),action)]=updated
        return updated

    def dump(self)->list[dict]:
        return [{"state":str(key[0]),"action":key[1],"q":value}
                for key,value in sorted(self.table.items(),key=lambda item:str(item[0]))]
