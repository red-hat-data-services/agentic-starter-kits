from typing import Literal
from pydantic import BaseModel


class PersonInformation(BaseModel):
    CheckingStatus: Literal["0_to_200", "less_0", "no_checking", "greater_200"]
    LoanDuration: float
    CreditHistory: Literal[
        "credits_paid_to_date",
        "prior_payments_delayed",
        "outstanding_credit",
        "all_credits_paid_back",
        "no_credits",
    ]
    LoanPurpose: Literal[
        "other",
        "car_new",
        "furniture",
        "retraining",
        "education",
        "vacation",
        "appliances",
        "car_used",
        "repairs",
        "radio_tv",
        "business",
    ]
    LoanAmount: float
    ExistingSavings: Literal[
        "100_to_500", "less_100", "500_to_1000", "unknown", "greater_1000"
    ]
    EmploymentDuration: Literal["less_1", "1_to_4", "greater_7", "4_to_7", "unemployed"]
    InstallmentPercent: float
    Sex: Literal["female", "male"]
    OthersOnLoan: Literal["none", "co-applicant", "guarantor"]
    CurrentResidenceDuration: float
    OwnsProperty: Literal["savings_insurance", "real_estate", "unknown", "car_other"]
    Age: float
    InstallmentPlans: Literal["none", "stores", "bank"]
    Housing: Literal["own", "free", "rent"]
    ExistingCreditsCount: float
    Job: Literal["skilled", "management_self-employed", "unskilled", "unemployed"]
    Dependents: float
    Telephone: Literal["none", "yes"]
    ForeignWorker: Literal["yes", "no"]
