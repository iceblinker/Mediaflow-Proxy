<<<<<<< HEAD
import logging
import psutil
from typing import Dict, Optional, List
from urllib.parse import urljoin
import xmltodict
from mediaflow_proxy.utils.http_utils import get_httpx_client
from mediaflow_proxy.configs import settings

logger = logging.getLogger(__name__)


class DASHPreBuffer:
    """
    Pre-buffer system for DASH streams to reduce latency and improve streaming performance.
    """
    
    def __init__(self, max_cache_size: Optional[int] = None, prebuffer_segments: Optional[int] = None):
        """
        Initialize the DASH pre-buffer system.
        
        Args:
            max_cache_size (int): Maximum number of segments to cache (uses config if None)
            prebuffer_segments (int): Number of segments to pre-buffer ahead (uses config if None)
        """
        self.max_cache_size = max_cache_size or settings.dash_prebuffer_cache_size
        self.prebuffer_segments = prebuffer_segments or settings.dash_prebuffer_segments
        self.max_memory_percent = settings.dash_prebuffer_max_memory_percent
        self.emergency_threshold = settings.dash_prebuffer_emergency_threshold
        
        # Cache for different types of DASH content
        self.segment_cache: Dict[str, bytes] = {}
        self.init_segment_cache: Dict[str, bytes] = {}
        self.manifest_cache: Dict[str, dict] = {}
        
        # Track segment URLs for each adaptation set
        self.adaptation_segments: Dict[str, List[str]] = {}
        self.client = get_httpx_client()
    
    def _get_memory_usage_percent(self) -> float:
        """
        Get current memory usage percentage.
        
        Returns:
            float: Memory usage percentage
        """
        try:
            memory = psutil.virtual_memory()
            return memory.percent
        except Exception as e:
            logger.warning(f"Failed to get memory usage: {e}")
            return 0.0
    
    def _check_memory_threshold(self) -> bool:
        """
        Check if memory usage exceeds the emergency threshold.
        
        Returns:
            bool: True if emergency cleanup is needed
        """
        memory_percent = self._get_memory_usage_percent()
        return memory_percent > self.emergency_threshold
    
    def _emergency_cache_cleanup(self) -> None:
        """
        Perform emergency cache cleanup when memory usage is high.
        """
        if self._check_memory_threshold():
            logger.warning("Emergency DASH cache cleanup triggered due to high memory usage")
            
            # Clear 50% of segment cache
            segment_cache_size = len(self.segment_cache)
            segment_keys_to_remove = list(self.segment_cache.keys())[:segment_cache_size // 2]
            for key in segment_keys_to_remove:
                del self.segment_cache[key]
            
            # Clear 50% of init segment cache
            init_cache_size = len(self.init_segment_cache)
            init_keys_to_remove = list(self.init_segment_cache.keys())[:init_cache_size // 2]
            for key in init_keys_to_remove:
                del self.init_segment_cache[key]
            
            logger.info(f"Emergency cleanup removed {len(segment_keys_to_remove)} segments and {len(init_keys_to_remove)} init segments from cache")
    
    async def prebuffer_dash_manifest(self, mpd_url: str, headers: Dict[str, str]) -> None:
        """
        Pre-buffer segments from a DASH manifest.
        
        Args:
            mpd_url (str): URL of the DASH manifest
            headers (Dict[str, str]): Headers to use for requests
        """
        try:
            # Download and parse MPD manifest
            response = await self.client.get(mpd_url, headers=headers)
            response.raise_for_status()
            mpd_content = response.text
            
            # Parse MPD XML
            mpd_dict = xmltodict.parse(mpd_content)
            
            # Store manifest in cache
            self.manifest_cache[mpd_url] = mpd_dict
            
            # Extract initialization segments and first few segments
            await self._extract_and_prebuffer_segments(mpd_dict, mpd_url, headers)
            
            logger.info(f"Pre-buffered DASH manifest: {mpd_url}")
            
        except Exception as e:
            logger.warning(f"Failed to pre-buffer DASH manifest {mpd_url}: {e}")
    
    async def _extract_and_prebuffer_segments(self, mpd_dict: dict, base_url: str, headers: Dict[str, str]) -> None:
        """
        Extract and pre-buffer segments from MPD manifest.
        
        Args:
            mpd_dict (dict): Parsed MPD manifest
            base_url (str): Base URL for resolving relative URLs
            headers (Dict[str, str]): Headers to use for requests
        """
        try:
            # Extract Period and AdaptationSet information
            mpd = mpd_dict.get('MPD', {})
            periods = mpd.get('Period', [])
            if not isinstance(periods, list):
                periods = [periods]
            
            for period in periods:
                adaptation_sets = period.get('AdaptationSet', [])
                if not isinstance(adaptation_sets, list):
                    adaptation_sets = [adaptation_sets]
                
                for adaptation_set in adaptation_sets:
                    # Extract initialization segment
                    init_segment = adaptation_set.get('SegmentTemplate', {}).get('@initialization')
                    if init_segment:
                        init_url = urljoin(base_url, init_segment)
                        await self._download_init_segment(init_url, headers)
                    
                    # Extract segment template
                    segment_template = adaptation_set.get('SegmentTemplate', {})
                    if segment_template:
                        await self._prebuffer_template_segments(segment_template, base_url, headers)
                    
                    # Extract segment list
                    segment_list = adaptation_set.get('SegmentList', {})
                    if segment_list:
                        await self._prebuffer_list_segments(segment_list, base_url, headers)
                        
        except Exception as e:
            logger.warning(f"Failed to extract segments from MPD: {e}")
    
    async def _download_init_segment(self, init_url: str, headers: Dict[str, str]) -> None:
        """
        Download and cache initialization segment.
        
        Args:
            init_url (str): URL of the initialization segment
            headers (Dict[str, str]): Headers to use for request
        """
        try:
            # Check memory usage before downloading
            memory_percent = self._get_memory_usage_percent()
            if memory_percent > self.max_memory_percent:
                logger.warning(f"Memory usage {memory_percent}% exceeds limit {self.max_memory_percent}%, skipping init segment download")
                return
            
            response = await self.client.get(init_url, headers=headers)
            response.raise_for_status()
            
            # Cache the init segment
            self.init_segment_cache[init_url] = response.content
            
            # Check for emergency cleanup
            if self._check_memory_threshold():
                self._emergency_cache_cleanup()
            
            logger.debug(f"Cached init segment: {init_url}")
            
        except Exception as e:
            logger.warning(f"Failed to download init segment {init_url}: {e}")
    
    async def _prebuffer_template_segments(self, segment_template: dict, base_url: str, headers: Dict[str, str]) -> None:
        """
        Pre-buffer segments using segment template.
        
        Args:
            segment_template (dict): Segment template from MPD
            base_url (str): Base URL for resolving relative URLs
            headers (Dict[str, str]): Headers to use for requests
        """
        try:
            media_template = segment_template.get('@media')
            if not media_template:
                return
            
            # Extract template parameters
            start_number = int(segment_template.get('@startNumber', 1))
            duration = float(segment_template.get('@duration', 0))
            timescale = float(segment_template.get('@timescale', 1))
            
            # Pre-buffer first few segments
            for i in range(self.prebuffer_segments):
                segment_number = start_number + i
                segment_url = media_template.replace('$Number$', str(segment_number))
                full_url = urljoin(base_url, segment_url)
                
                await self._download_segment(full_url, headers)
                
        except Exception as e:
            logger.warning(f"Failed to pre-buffer template segments: {e}")
    
    async def _prebuffer_list_segments(self, segment_list: dict, base_url: str, headers: Dict[str, str]) -> None:
        """
        Pre-buffer segments from segment list.
        
        Args:
            segment_list (dict): Segment list from MPD
            base_url (str): Base URL for resolving relative URLs
            headers (Dict[str, str]): Headers to use for requests
        """
        try:
            segments = segment_list.get('SegmentURL', [])
            if not isinstance(segments, list):
                segments = [segments]
            
            # Pre-buffer first few segments
            for segment in segments[:self.prebuffer_segments]:
                segment_url = segment.get('@src')
                if segment_url:
                    full_url = urljoin(base_url, segment_url)
                    await self._download_segment(full_url, headers)
                    
        except Exception as e:
            logger.warning(f"Failed to pre-buffer list segments: {e}")
    
    async def _download_segment(self, segment_url: str, headers: Dict[str, str]) -> None:
        """
        Download a single segment and cache it.
        
        Args:
            segment_url (str): URL of the segment to download
            headers (Dict[str, str]): Headers to use for request
        """
        try:
            # Check memory usage before downloading
            memory_percent = self._get_memory_usage_percent()
            if memory_percent > self.max_memory_percent:
                logger.warning(f"Memory usage {memory_percent}% exceeds limit {self.max_memory_percent}%, skipping segment download")
                return
            
            response = await self.client.get(segment_url, headers=headers)
            response.raise_for_status()
            
            # Cache the segment
            self.segment_cache[segment_url] = response.content
            
            # Check for emergency cleanup
            if self._check_memory_threshold():
                self._emergency_cache_cleanup()
            # Maintain cache size
            elif len(self.segment_cache) > self.max_cache_size:
                # Remove oldest entries (simple FIFO)
                oldest_key = next(iter(self.segment_cache))
                del self.segment_cache[oldest_key]
                
            logger.debug(f"Cached DASH segment: {segment_url}")
            
        except Exception as e:
            logger.warning(f"Failed to download DASH segment {segment_url}: {e}")
    
    async def get_segment(self, segment_url: str, headers: Dict[str, str]) -> Optional[bytes]:
        """
        Get a segment from cache or download it.
        
        Args:
            segment_url (str): URL of the segment
            headers (Dict[str, str]): Headers to use for request
            
        Returns:
            Optional[bytes]: Cached segment data or None if not available
        """
        # Check segment cache first
        if segment_url in self.segment_cache:
            logger.debug(f"DASH cache hit for segment: {segment_url}")
            return self.segment_cache[segment_url]
        
        # Check init segment cache
        if segment_url in self.init_segment_cache:
            logger.debug(f"DASH cache hit for init segment: {segment_url}")
            return self.init_segment_cache[segment_url]
        
        # Check memory usage before downloading
        memory_percent = self._get_memory_usage_percent()
        if memory_percent > self.max_memory_percent:
            logger.warning(f"Memory usage {memory_percent}% exceeds limit {self.max_memory_percent}%, skipping download")
            return None
        
        # Download if not in cache
        try:
            response = await self.client.get(segment_url, headers=headers)
            response.raise_for_status()
            segment_data = response.content
            
            # Determine if it's an init segment or regular segment
            if 'init' in segment_url.lower() or segment_url.endswith('.mp4'):
                self.init_segment_cache[segment_url] = segment_data
            else:
                self.segment_cache[segment_url] = segment_data
            
            # Check for emergency cleanup
            if self._check_memory_threshold():
                self._emergency_cache_cleanup()
            # Maintain cache size
            elif len(self.segment_cache) > self.max_cache_size:
                oldest_key = next(iter(self.segment_cache))
                del self.segment_cache[oldest_key]
            
            logger.debug(f"Downloaded and cached DASH segment: {segment_url}")
            return segment_data
            
        except Exception as e:
            logger.warning(f"Failed to get DASH segment {segment_url}: {e}")
            return None
    
    async def get_manifest(self, mpd_url: str, headers: Dict[str, str]) -> Optional[dict]:
        """
        Get MPD manifest from cache or download it.
        
        Args:
            mpd_url (str): URL of the MPD manifest
            headers (Dict[str, str]): Headers to use for request
            
        Returns:
            Optional[dict]: Cached manifest data or None if not available
        """
        # Check cache first
        if mpd_url in self.manifest_cache:
            logger.debug(f"DASH cache hit for manifest: {mpd_url}")
            return self.manifest_cache[mpd_url]
        
        # Download if not in cache
        try:
            response = await self.client.get(mpd_url, headers=headers)
            response.raise_for_status()
            mpd_content = response.text
            mpd_dict = xmltodict.parse(mpd_content)
            
            # Cache the manifest
            self.manifest_cache[mpd_url] = mpd_dict
            
            logger.debug(f"Downloaded and cached DASH manifest: {mpd_url}")
            return mpd_dict
            
        except Exception as e:
            logger.warning(f"Failed to get DASH manifest {mpd_url}: {e}")
            return None
    
    def clear_cache(self) -> None:
        """Clear the DASH cache."""
        self.segment_cache.clear()
        self.init_segment_cache.clear()
        self.manifest_cache.clear()
        self.adaptation_segments.clear()
        logger.info("DASH pre-buffer cache cleared")
    
    async def close(self) -> None:
        """Close the pre-buffer system."""
        # Do not close the shared client
        pass


# Global DASH pre-buffer instance
dash_prebuffer = DASHPreBuffer() 
=======
"""
DASH Pre-buffer system for reducing latency and improving streaming performance.

This module extends BasePrebuffer with DASH-specific functionality including
MPD parsing integration, profile handling, and init segment management.
"""

import asyncio
import logging
import time
from typing import Dict, Optional, List

from mediaflow_proxy.utils.base_prebuffer import BasePrebuffer
from mediaflow_proxy.utils.cache_utils import (
    get_cached_mpd,
    get_cached_init_segment,
)
from mediaflow_proxy.configs import settings

logger = logging.getLogger(__name__)


class DASHPreBuffer(BasePrebuffer):
    """
    Pre-buffer system for DASH streams.

    Extends BasePrebuffer with DASH-specific features:
    - MPD manifest parsing and profile handling
    - Init segment prebuffering
    - Live stream segment tracking
    - Profile-based segment prefetching

    Uses event-based download coordination from BasePrebuffer to prevent
    duplicate downloads between player requests and background prebuffering.
    """

    def __init__(
        self,
        max_cache_size: Optional[int] = None,
        prebuffer_segments: Optional[int] = None,
    ):
        """
        Initialize the DASH pre-buffer system.

        Args:
            max_cache_size: Maximum number of segments to cache (uses config if None)
            prebuffer_segments: Number of segments to pre-buffer ahead (uses config if None)
        """
        super().__init__(
            max_cache_size=max_cache_size or settings.dash_prebuffer_cache_size,
            prebuffer_segments=prebuffer_segments or settings.dash_prebuffer_segments,
            max_memory_percent=settings.dash_prebuffer_max_memory_percent,
            emergency_threshold=settings.dash_prebuffer_emergency_threshold,
            segment_ttl=settings.dash_segment_cache_ttl,
        )

        self.inactivity_timeout = settings.dash_prebuffer_inactivity_timeout

        # DASH-specific state
        # Track active streams for prefetching: mpd_url -> stream_info
        self.active_streams: Dict[str, dict] = {}
        self.prefetch_tasks: Dict[str, asyncio.Task] = {}

        # Additional stats for DASH
        self.init_segments_prebuffered = 0

        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None

    def log_stats(self) -> None:
        """Log current prebuffer statistics with DASH-specific info."""
        stats = self.stats.to_dict()
        stats["init_segments_prebuffered"] = self.init_segments_prebuffered
        stats["active_streams"] = len(self.active_streams)
        logger.info(f"DASH Prebuffer Stats: {stats}")

    async def prebuffer_dash_manifest(
        self,
        mpd_url: str,
        headers: Dict[str, str],
    ) -> None:
        """
        Pre-buffer segments from a DASH manifest using existing MPD parsing.

        Args:
            mpd_url: URL of the DASH manifest
            headers: Headers to use for requests
        """
        try:
            # First get the basic MPD info without segments
            parsed_mpd = await get_cached_mpd(mpd_url, headers, parse_drm=False)
            if not parsed_mpd:
                logger.warning(f"Failed to get parsed MPD for prebuffering: {mpd_url}")
                return

            is_live = parsed_mpd.get("isLive", False)
            base_profiles = parsed_mpd.get("profiles", [])

            if not base_profiles:
                logger.warning(f"No profiles found in MPD for prebuffering: {mpd_url}")
                return

            # Now get segments for each profile by parsing with profile_id
            profiles_with_segments = []
            for profile in base_profiles:
                profile_id = profile.get("id")
                if profile_id:
                    parsed_with_segments = await get_cached_mpd(
                        mpd_url, headers, parse_drm=False, parse_segment_profile_id=profile_id
                    )
                    # Find the matching profile with segments
                    for p in parsed_with_segments.get("profiles", []):
                        if p.get("id") == profile_id:
                            profiles_with_segments.append(p)
                            break

            # Store stream info for ongoing prefetching
            self.active_streams[mpd_url] = {
                "headers": headers,
                "is_live": is_live,
                "profiles": profiles_with_segments,
                "last_access": time.time(),
            }

            # Prebuffer init segments and media segments
            await self._prebuffer_profiles(profiles_with_segments, headers, is_live)

            # Start cleanup task if not running
            self._ensure_cleanup_task_running()

            logger.info(
                f"Pre-buffered DASH manifest: {mpd_url} (live={is_live}, profiles={len(profiles_with_segments)})"
            )

        except Exception as e:
            logger.warning(f"Failed to pre-buffer DASH manifest {mpd_url}: {e}")

    async def _prebuffer_profiles(
        self,
        profiles: List[dict],
        headers: Dict[str, str],
        is_live: bool = False,
    ) -> None:
        """
        Pre-buffer init segments and media segments for all profiles.

        For live streams, prebuffers from the END of the segment list.
        For VOD, prebuffers from the beginning.

        Args:
            profiles: List of parsed profiles with resolved URLs
            headers: Headers to use for requests
            is_live: Whether this is a live stream
        """
        if self._should_skip_for_memory():
            logger.warning("Memory usage too high, skipping prebuffer")
            return

        # Collect all segment URLs to prebuffer
        segment_urls = []
        init_urls = []

        for profile in profiles:
            # Collect init segment URL
            init_url = profile.get("initUrl")
            if init_url:
                init_urls.append(init_url)

            # Get segments to prebuffer
            segments = profile.get("segments", [])
            if not segments:
                continue

            # For live streams, prebuffer from the END (most recent)
            if is_live:
                segments_to_buffer = segments[-self.prebuffer_segment_count :]
            else:
                segments_to_buffer = segments[: self.prebuffer_segment_count]

            for segment in segments_to_buffer:
                segment_url = segment.get("media")
                if segment_url:
                    segment_urls.append(segment_url)

        # Prebuffer init segments (using special init cache)
        for init_url in init_urls:
            asyncio.create_task(self._prebuffer_init_segment(init_url, headers))

        # Prebuffer media segments using base class method
        if segment_urls:
            await self.prebuffer_segments_batch(segment_urls, headers)

    async def _prebuffer_init_segment(
        self,
        init_url: str,
        headers: Dict[str, str],
    ) -> None:
        """
        Prebuffer an init segment using the init segment cache.

        Args:
            init_url: URL of the init segment
            headers: Headers for the request
        """
        try:
            # get_cached_init_segment handles both caching and downloading
            content = await get_cached_init_segment(init_url, headers)
            if content:
                self.init_segments_prebuffered += 1
                self.stats.bytes_prebuffered += len(content)
                logger.debug(f"Prebuffered init segment ({len(content)} bytes)")
        except Exception as e:
            logger.warning(f"Failed to prebuffer init segment: {e}")

    async def prefetch_upcoming_segments(
        self,
        mpd_url: str,
        current_segment_url: str,
        headers: Dict[str, str],
        profile_id: Optional[str] = None,
    ) -> None:
        """
        Prefetch upcoming segments based on current playback position.

        Called when a segment is requested to prefetch the next N segments.

        Args:
            mpd_url: URL of the MPD manifest
            current_segment_url: URL of the currently requested segment
            headers: Headers to use for requests
            profile_id: Optional profile ID to limit prefetching to
        """
        self.stats.prefetch_triggered += 1

        try:
            # First check if we have cached profiles with segments
            if mpd_url in self.active_streams:
                # Update last access time
                self.active_streams[mpd_url]["last_access"] = time.time()
                profiles = self.active_streams[mpd_url].get("profiles", [])
            else:
                # Get parsed MPD
                parsed_mpd = await get_cached_mpd(mpd_url, headers, parse_drm=False)
                if not parsed_mpd:
                    return
                profiles = parsed_mpd.get("profiles", [])

            for profile in profiles:
                pid = profile.get("id")
                if profile_id and pid != profile_id:
                    continue

                segments = profile.get("segments", [])

                # If no segments, try to get them by parsing with profile_id
                if not segments and pid:
                    parsed_with_segments = await get_cached_mpd(
                        mpd_url, headers, parse_drm=False, parse_segment_profile_id=pid
                    )
                    for p in parsed_with_segments.get("profiles", []):
                        if p.get("id") == pid:
                            segments = p.get("segments", [])
                            break

                # Find current segment index
                current_index = -1
                for i, segment in enumerate(segments):
                    if segment.get("media") == current_segment_url:
                        current_index = i
                        break

                if current_index < 0:
                    continue

                # Collect next N segment URLs
                segment_urls = []
                end_index = min(current_index + 1 + self.prebuffer_segment_count, len(segments))
                for i in range(current_index + 1, end_index):
                    segment_url = segments[i].get("media")
                    if segment_url:
                        segment_urls.append(segment_url)

                if segment_urls:
                    logger.debug(f"Prefetching {len(segment_urls)} upcoming segments from index {current_index + 1}")
                    # Run prefetch in background
                    asyncio.create_task(self.prebuffer_segments_batch(segment_urls, headers, max_concurrent=3))

        except Exception as e:
            logger.warning(f"Failed to prefetch upcoming segments: {e}")

    async def prefetch_for_live_playlist(
        self,
        profiles: List[dict],
        headers: Dict[str, str],
    ) -> None:
        """
        Prefetch segments for a live playlist refresh.

        Called from process_playlist to ensure upcoming segments are cached.

        Args:
            profiles: List of profiles with resolved segment URLs
            headers: Headers to use for requests
        """
        segment_urls = []

        for profile in profiles:
            segments = profile.get("segments", [])
            if not segments:
                continue

            # For live, prefetch the last N segments (most recent)
            segments_to_prefetch = segments[-self.prebuffer_segment_count :]

            for segment in segments_to_prefetch:
                segment_url = segment.get("media")
                if segment_url:
                    # Check if already cached before adding
                    cached = await self.try_get_cached(segment_url)
                    if not cached:
                        segment_urls.append(segment_url)

        if segment_urls:
            logger.debug(f"Live playlist prefetch: {len(segment_urls)} segments")
            asyncio.create_task(self.prebuffer_segments_batch(segment_urls, headers, max_concurrent=3))

    def _ensure_cleanup_task_running(self) -> None:
        """Ensure the cleanup task is running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_inactive_streams())

    async def _cleanup_inactive_streams(self) -> None:
        """
        Periodically check for and clean up inactive streams.

        Runs in the background and removes streams that haven't been
        accessed recently.
        """
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                if not self.active_streams:
                    logger.debug("No active DASH streams to monitor, stopping cleanup")
                    return

                current_time = time.time()
                streams_to_remove = []

                for mpd_url, stream_info in self.active_streams.items():
                    last_access = stream_info.get("last_access", 0)
                    time_since_access = current_time - last_access

                    if time_since_access > self.inactivity_timeout:
                        streams_to_remove.append(mpd_url)
                        logger.info(f"Cleaning up inactive DASH stream ({time_since_access:.0f}s idle)")

                # Remove inactive streams
                for mpd_url in streams_to_remove:
                    self.active_streams.pop(mpd_url, None)
                    task = self.prefetch_tasks.pop(mpd_url, None)
                    if task:
                        task.cancel()

                if streams_to_remove:
                    logger.info(f"Cleaned up {len(streams_to_remove)} inactive DASH stream(s)")

            except asyncio.CancelledError:
                logger.debug("DASH cleanup task cancelled")
                return
            except Exception as e:
                logger.warning(f"Error in DASH cleanup task: {e}")

    def get_stats(self) -> dict:
        """Get current prebuffer statistics."""
        stats = self.stats.to_dict()
        stats["init_segments_prebuffered"] = self.init_segments_prebuffered
        stats["active_streams"] = len(self.active_streams)
        return stats

    def clear_cache(self) -> None:
        """Clear active streams tracking and log final stats."""
        self.log_stats()
        self.active_streams.clear()
        for task in self.prefetch_tasks.values():
            task.cancel()
        self.prefetch_tasks.clear()
        # Cancel cleanup task
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        self._cleanup_task = None
        self.stats.reset()
        self.init_segments_prebuffered = 0
        logger.info("DASH pre-buffer state cleared")

    async def close(self) -> None:
        """Close the pre-buffer system."""
        self.clear_cache()


# Global DASH pre-buffer instance
dash_prebuffer = DASHPreBuffer()
>>>>>>> upstream/main
