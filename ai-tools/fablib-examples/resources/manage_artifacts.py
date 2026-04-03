# FABRIC Artifact Manager
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: manage_artifacts.ipynb
#
# Reproducibility is a core principle of scientific research — your experiment
# should produce the same results when run by a collaborator on a different day.
# The [FABRIC Artifacts Manager](https://ar...

# # FABRIC Artifact Manager
# ### FABlib API References
# ### External References

# ## Step 1: Configure the Environment and Import FABlib

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()

fablib.show_config();


# ## Step 2: List All Accessible Artifacts

fablib.list_artifacts();


# ## Step 3: Define a New Artifact

# Define the artifact details
artifact_title = "Test-Artifact"
description_short = "Short Description"
description_long = "Long Description"
tags = ["example"]
visibility = "project"  # Options: "author", "project", "public"
authors = []  # List of author email addresses; if empty, use the user's token

artifact = fablib.create_artifact(artifact_title=artifact_title,
                                  description_short=description_short,
                                  description_long=description_long,
                                  tags=tags,
                                  visibility=visibility,
                                  authors=authors)


# ## Step 4: Create the Artifact

# ## Step 5: Verify the New Artifact

fablib.list_artifacts(filter_function=lambda x: x['title']==artifact_title);


# ## Step 6: Upload Files to the Artifact

file_to_upload = "./hello_fabric.tgz"

artifact = fablib.get_artifacts(artifact_title=artifact_title)[0].to_dict()

upload_response = fablib.upload_file_to_artifact(artifact_id=artifact.get("uuid"), 
                                                 file_to_upload=file_to_upload)

print(f"Uploaded tar file to artifact: {upload_response}")


# ## Step 7: Verify the Upload

fablib.list_artifacts(filter_function=lambda x: x['title']==artifact_title);


# ## Step 8: Delete the Artifact

fablib.delete_artifact(artifact_title=artifact_title);


# ## Step 9: Confirm Deletion

fablib.list_artifacts(filter_function=lambda x: x['title']==artifact_title);

# ## Continue Learning
