from unittest.mock import patch

import pytest
from stock_analysis.execution.services import account_snapshot

pytestmark = pytest.mark.unit


def test_get_multiple_account_snapshots():
    with patch(
        "stock_analysis.execution.services.account_snapshot.get_account_snapshot"
    ) as mock_get:
        mock_get.side_effect = ["snap1", "snap2"]
        snaps = account_snapshot.get_multiple_account_snapshots(["env1", "env2"])
        assert snaps == ["snap1", "snap2"]
        mock_get.assert_any_call(env="env1")
        mock_get.assert_any_call(env="env2")
