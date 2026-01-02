
import pytest
from unittest.mock import MagicMock
from mediaflow_proxy.utils.m3u8_processor import M3U8Processor

@pytest.mark.asyncio
async def test_m3u8_processor_filtering():
    manifest = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",LANGUAGE="en",NAME="English",URI="english.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",LANGUAGE="es",NAME="Spanish",URI="spanish.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360,AUDIO="audio"
360p.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1400000,RESOLUTION=842x480,AUDIO="audio"
480p.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION=1280x720,AUDIO="audio"
720p.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,AUDIO="audio"
1080p.m3u8
"""
    # Mock Request
    mock_request = MagicMock()
    # Mock URL object returned by url_for
    mock_url = MagicMock()
    mock_url.replace.return_value = "http://localhost/proxy" # simplified for test
    mock_url.__str__.return_value = "http://localhost/proxy"
    mock_request.url_for.return_value = mock_url
    mock_request.query_params = {}

    # Test Quality Filtering (720p)
    processor = M3U8Processor(mock_request, quality=720)
    filtered = processor._apply_filtering(manifest)
    
    assert "RESOLUTION=1280x720" in filtered
    assert "720p.m3u8" in filtered
    assert "RESOLUTION=640x360" not in filtered
    assert "RESOLUTION=1920x1080" not in filtered

    # Test Language Filtering (es)
    processor_lang = M3U8Processor(mock_request, language="es")
    filtered_lang = processor_lang._apply_filtering(manifest)
    
    assert 'LANGUAGE="es"' in filtered_lang
    assert 'LANGUAGE="en"' not in filtered_lang

    # Test Combined
    processor_combo = M3U8Processor(mock_request, quality=1080, language="en")
    filtered_combo = processor_combo._apply_filtering(manifest)
    
    assert "RESOLUTION=1920x1080" in filtered_combo
    assert 'LANGUAGE="en"' in filtered_combo
    assert "RESOLUTION=720p" not in filtered_combo
    assert 'LANGUAGE="es"' not in filtered_combo
