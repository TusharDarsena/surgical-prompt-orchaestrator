import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.fixture
def tmp_spo_data_dir(tmp_path):
    """
    Overrides the SPO_DATA_DIR environment variable to point to a temporary
    directory. This ensures that storage.py reads/writes real JSON files
    to a sandbox, catching serialization issues or path errors.
    """
    old_val = os.environ.get("SPO_DATA_DIR")
    os.environ["SPO_DATA_DIR"] = str(tmp_path)
    yield tmp_path
    if old_val is None:
        del os.environ["SPO_DATA_DIR"]
    else:
        os.environ["SPO_DATA_DIR"] = old_val


@pytest.fixture
def mock_nlm_client():
    """
    Mocks the `_nlm_client` async context manager from `notebooklm_service.py`
    and returns the underlying mocked client so tests can configure return values
    and side effects.
    """
    mock_client = AsyncMock()
    
    # Mock specific sub-clients and their methods
    mock_client.chat = AsyncMock()
    mock_client.sources = AsyncMock()
    mock_client.notebooks = AsyncMock()
    
    # Set up default successful behaviors
    
    # notebooks.create returns an object with an id
    mock_nb = MagicMock()
    mock_nb.id = "mock_notebook_id"
    mock_client.notebooks.create.return_value = mock_nb
    
    # chat.ask returns an object with .answer
    mock_result = MagicMock()
    mock_result.answer = "Mocked LLM answer text"
    mock_client.chat.ask.return_value = mock_result
    
    # sources.add_text returns an object with .id
    mock_src = MagicMock()
    mock_src.id = "mock_source_id"
    mock_client.sources.add_text.return_value = mock_src
    
    # sources.list returns an empty list by default
    mock_client.sources.list.return_value = []
    
    # The context manager itself: async with _nlm_client() as client:
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_client
    mock_context_manager.__aexit__.return_value = None

    # We patch the exact namespace where it's imported/used in notebooklm_service
    # and in routers.notebooklm
    patch1 = patch("services.notebooklm_service._nlm_client", return_value=mock_context_manager)
    patch2 = patch("routers.notebooklm._nlm_client", return_value=mock_context_manager)
    
    with patch1, patch2:
        yield mock_client


@pytest.fixture
def mock_gdocs_client():
    """
    Mocks the `_gdocs_client` async context manager from `google_docs_service.py`
    and returns the underlying mocked client so tests can configure return values
    and side effects.
    """
    mock_client = AsyncMock()
    
    # Mock specific sub-clients and their methods
    mock_client.documents = MagicMock()
    
    mock_doc_methods = MagicMock()
    mock_client.documents.return_value = mock_doc_methods
    
    # Set up default successful behaviors
    
    # documents().create().execute() returns an object with a documentId
    mock_create_req = MagicMock()
    mock_create_req.execute.return_value = {"documentId": "mock_gdoc_id"}
    mock_doc_methods.create.return_value = mock_create_req
    
    # documents().get().execute() returns a doc with body and namedRanges
    mock_get_req = MagicMock()
    mock_get_req.execute.return_value = {
        "body": {"content": [{"endIndex": 100}]},
        "namedRanges": {}
    }
    mock_doc_methods.get.return_value = mock_get_req
    
    # documents().batchUpdate().execute() returns replies
    mock_batch_req = MagicMock()
    mock_batch_req.execute.return_value = {
        "replies": [{"createNamedRange": {"namedRangeId": "mock_named_range_id"}}]
    }
    mock_doc_methods.batchUpdate.return_value = mock_batch_req
    
    # The context manager itself: async with _gdocs_client() as client:
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_client
    mock_context_manager.__aexit__.return_value = None

    # We patch the exact namespace where it's imported/used in google_docs_service
    # and in routers.gdocs (if used there)
    patch1 = patch("services.google_docs_service._gdocs_client", return_value=mock_context_manager)
    
    with patch1:
        yield mock_client
