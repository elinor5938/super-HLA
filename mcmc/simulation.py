import random
import pandas as pd

from pipeline import (
    peptide_creator, send_pep_to_prediction, mutation_creator, 
    check_delta, first_pep_init
)
from parameters import get_probability_function

OPTIMIZATION_COLUMN = "sum_of_all_hla"

def simulation_process(seed: int, external_peptide_str=None, number_of_accepted_peptides=2) -> pd.DataFrame:
    """Gets a peptide and column to calculate the simulation function and return df with all the results."""
    import time
    import sys

    random.seed(seed)
    appended_data = pd.DataFrame()

    if external_peptide_str is None:
        peptide = peptide_creator(9)
        print(f"  [MCMC] Generated random starting peptide: {peptide}")
    else:
        peptide = external_peptide_str
        print(f"  [MCMC] Using external peptide: {peptide}")

    print(f"  [MCMC] Running initial MHC binding prediction...")
    first_pep_df = first_pep_init(peptide, seed)
    initial_score = first_pep_df[OPTIMIZATION_COLUMN].values[0]
    initial_binders = int(first_pep_df["total_binders"].values[0]) if "total_binders" in first_pep_df.columns else "N/A"
    print(f"  [MCMC] Initial: sum_of_all_hla={initial_score:.4f}, total_binders={initial_binders}")
    appended_data = pd.concat([appended_data, first_pep_df], ignore_index=True)

    last_true_val = None
    last_true_pep = None
    iteration = 0
    accepted_count = 0
    t_start = time.time()

    print(f"  [MCMC] Starting MCMC loop (target: {number_of_accepted_peptides} accepted mutations)...")
    sys.stdout.flush()

    while True:
        iteration += 1
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
            current_binders = int(appended_data.tail(1)["total_binders"].values[0]) if "total_binders" in appended_data.columns else "N/A"
            accepted_count += 1
            print(f"  [MCMC] Iteration {iteration}: ACCEPTED ({accepted_count}/{number_of_accepted_peptides}) "
                  f"| {former_aa}{position}->{new_aa} | peptide={peptide} "
                  f"| sum_of_all_hla={last_true_val:.4f} | total_binders={current_binders}")
            sys.stdout.flush()
        else:
            if last_true_pep is not None:
                peptide = last_true_pep  # Fallback to last accepted
            else:
                # If there's no accepted step before, go back to the first initial peptide
                peptide = first_pep_df.head(1)["Peptide"].values[0]
                last_true_val = first_pep_df.head(1)[OPTIMIZATION_COLUMN].values[0]

        # Progress update every 10 iterations (for rejected ones)
        if iteration % 10 == 0 and not acceptance_flag:
            elapsed = time.time() - t_start
            print(f"  [MCMC] Iteration {iteration}: {accepted_count}/{number_of_accepted_peptides} accepted "
                  f"({elapsed:.0f}s elapsed)")
            sys.stdout.flush()

        # Break out when we reach target accepted count
        total_accepted = (appended_data["mcmc_accepted"] == True).sum()  # noqa: E712
        if total_accepted >= number_of_accepted_peptides:
            break

    elapsed = time.time() - t_start
    print(f"  [MCMC] Complete: {iteration} iterations, {number_of_accepted_peptides} accepted in {elapsed:.1f}s")
    sys.stdout.flush()

    return appended_data
