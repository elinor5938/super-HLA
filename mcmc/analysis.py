import numpy as np
import pandas as pd
from config import SUPERTYPES_LIST

def create_df_from_netmhcpan_output(df: pd.DataFrame, supertypes_list: list = SUPERTYPES_LIST) -> pd.DataFrame:
    """Get netMHCpan output as a df and process it."""
    mutant_df = df[df["MHC"].isin(supertypes_list)]

    # Pivot so rows are Peptides and columns are MHC types
    data_hla_as_col = mutant_df.pivot(columns="MHC", values="%Rank_EL", index="Peptide")
    data_hla_as_col = data_hla_as_col.astype(float)

    # Count Weak Binders (WB), Strong Binders (SB), and Non-Binders (NB)
    data_hla_as_col["WB"] = data_hla_as_col[(0.5 < data_hla_as_col.loc[:, supertypes_list]) & (data_hla_as_col.loc[:, supertypes_list] <= 2)].count(axis=1)
    data_hla_as_col["SB"] = data_hla_as_col[data_hla_as_col.loc[:, supertypes_list] <= 0.5].count(axis=1)
    data_hla_as_col["NB"] = data_hla_as_col[data_hla_as_col.loc[:, supertypes_list] > 2].count(axis=1)
    
    # Calculate deltas (these are likely meant to capture differences if index is sequential, 
    # but the original code did it globally returning a column. It might be used inside a simulation loop where order matters)
    data_hla_as_col["WB_delta"] = pd.Series([0] + list(np.round(np.diff(data_hla_as_col["WB"]), 5)))
    data_hla_as_col["NB_delta"] = pd.Series([0] + list(np.round(np.diff(data_hla_as_col["NB"]), 5)))
    data_hla_as_col["SB_delta"] = pd.Series([0] + list(np.round(np.diff(data_hla_as_col["SB"]), 5)))
    
    # Sum of all HLA ranks (the key optimization metric)
    data_hla_as_col["sum_of_all_hla"] = data_hla_as_col.loc[:, supertypes_list].sum(axis=1)
    
    # Resetting index to make Peptide a regular column
    data_hla_as_col.reset_index(inplace=True)
    
    # Keeping track of specific HLA types that fall into the categories
    wb_id = data_hla_as_col[supertypes_list][(0.5 < data_hla_as_col[supertypes_list]) & (data_hla_as_col[supertypes_list] <= 2)].apply(lambda x: x.dropna().index.tolist(), axis=1)
    sb_id = data_hla_as_col[supertypes_list][data_hla_as_col[supertypes_list] <= 0.5].apply(lambda x: x.dropna().index.tolist(), axis=1)
    nb_id = data_hla_as_col[supertypes_list][data_hla_as_col[supertypes_list] > 2].apply(lambda x: x.dropna().index.tolist(), axis=1)
    
    data_hla_as_col["wb_id"] = wb_id
    data_hla_as_col["sb_id"] = sb_id
    data_hla_as_col["nb_id"] = nb_id
    data_hla_as_col["total_binders_id"] = data_hla_as_col["wb_id"] + data_hla_as_col["sb_id"]
    
    data_hla_as_col.fillna(0, inplace=True)
    
    # Total valid binders
    data_hla_as_col["total_binders"] = data_hla_as_col["SB"] + data_hla_as_col["WB"]
    
    return data_hla_as_col
