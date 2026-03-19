import random
import pandas as pd

from pipeline import (
    peptide_creator, send_pep_to_prediction, mutation_creator, 
    check_delta, firs_pep_init
)
from parameters import get_probability_function

OPTIMIZATION_COLUMN = "sum_of_all_hla"

def simulation_process(seed: int, external_peptide_str=None, number_of_accepted_peptides=2) -> pd.DataFrame:
    """Gets a peptide and column to calculate the simulation function and return df with all the results."""
    random.seed(seed)
    appended_data = pd.DataFrame()
    
    if external_peptide_str is None:
        peptide = peptide_creator(9)
    else:
        peptide = external_peptide_str

    first_pep_df = firs_pep_init(peptide, seed)
    appended_data = pd.concat([appended_data, first_pep_df], ignore_index=True)

    last_true_val = None
    last_true_pep = None
    
    while True:
        peptide, position, former_aa, new_aa = mutation_creator(peptide)
        current = send_pep_to_prediction(peptide, seed)
        
        current.loc[current.index[-1], "position_changed"] = position
        current.loc[current.index[-1], "former_AA"] = former_aa
        current.loc[current.index[-1], "new_AA"] = new_aa
        
        appended_data = pd.concat([appended_data, current], ignore_index=True)
        
        # Checking probability
        appended_data, acceptance_flag = check_delta(
            appended_data, 
            get_probability_function, 
            OPTIMIZATION_COLUMN,
            last_true_val
        )
        
        if acceptance_flag:
            last_true_pep = peptide
            last_true_val = appended_data.tail(1)[OPTIMIZATION_COLUMN].values[0]
        else:
            if last_true_pep is not None:
                peptide = last_true_pep  # Fallback to last accepted
            else:
                # If there's no accepted step before, go back to the first initial peptide
                peptide = first_pep_df.head(1)["Peptide"].values[0]
                last_true_val = first_pep_df.head(1)[OPTIMIZATION_COLUMN].values[0]

        # Break out when we reach target accepted count
        accepted_count = (appended_data["probabilty_res_MCMC"] == True).sum()  # noqa: E712
        if accepted_count >= number_of_accepted_peptides:
            break
            
    return appended_data
