# List Slices
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: list_slices.ipynb
#
# This notebook demonstrates how to query and display all your FABRIC slices.
# `fablib.list_slices()` is your primary tool for getting an overview of what
# experiments you have running, checking their ...

# # List Slices
# ### FABlib API References

# ## Step 1: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: List All Slices

fablib.list_slices();


# ## Step 3: Filter Displayed Fields

fablib.list_slices(fields=['name','state']);


# ## Step 4: Filter by Field Values

fablib.list_slices(filter_function=lambda x: x['state'] == 'StableOK' );


# ## Step 5: Output Formats

output_dataframe = fablib.list_slices(output='pandas')


# ### Output as Plain Text

output_table_string = fablib.list_slices(output='text')


# ### Output as JSON

output_json = fablib.list_slices(output='json')


# ### Output as Python List of Dicts

output_list = fablib.list_slices(output='list');

output_list = fablib.list_slices(output='list', quiet=True)
    
for slice in output_list:
    print(f"Slice: {slice['id']}, {slice['name']}, {slice['state']}")


# ## Step 6: Custom Display with Color-Coded States
# ## Continue Learning

import pandas as pd
from IPython.display import clear_output


def state_color(val):
    if val == 'StableOK':
        color = f'{fablib.SUCCESS_LIGHT_COLOR}'
    elif val == 'Configuring' or val == 'Modifying' or val == 'ModifyOK':
        color = f'{fablib.IN_PROGRESS_LIGHT_COLOR}'
    elif val == 'StableError':
        color = f'{fablib.ERROR_LIGHT_COLOR}'
        
    else:
        color = ''
    return 'background-color: %s' % color


clear_output(wait=True)


pandas_dataframe = fablib.list_slices(output='pandas', quiet=True)
pandas_dataframe = pandas_dataframe.applymap(state_color, subset=pd.IndexSlice[:, ['State']]) 
    
display(pandas_dataframe)

#
