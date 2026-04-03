# Common FABRIC Tools and Features
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: fablib_common.ipynb

# # Common FABRIC Tools and Features
# ## Random Sites

site = fablib.get_random_site()


# ## Logging

logging.info(f"message for log")

fablib.set_log_file("/path/to/log/file")
fablib.set_log_levle("DEBUG")


# ## Lists and Tables

# ### List Objects

fablib.list_sites()


# ### Show Objects

node.show()


# ### Specify Fields

fablib.list_sites(fields=['Name','ConnectX-6 Available', 'RTX6000 Available'])


# ### Filter by Value

fablib.list_sites(filter_function=lambda x: x['RTX6000 Available'] > 3)
