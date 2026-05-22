# Re-export shared integration fixtures so pytest discovers them.
from integration.conftest import cluster_auth, repo_root  # noqa: F401
