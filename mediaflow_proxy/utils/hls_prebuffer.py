<<<<<<< HEAD
import asyncio
import logging
import psutil
from typing import Dict, Optional, List
from urllib.parse import urlparse
import httpx
from mediaflow_proxy.utils.http_utils import get_httpx_client
from mediaflow_proxy.configs import settings
from collections import OrderedDict
import time
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


class HLSPreBuffer:
    """
    Pre-buffer system for HLS streams to reduce latency and improve streaming performance.
    """
    
    def __init__(self, max_cache_size: Optional[int] = None, prebuffer_segments: Optional[int] = None):
        """
        Initialize the HLS pre-buffer system.
        
        Args:
            max_cache_size (int): Maximum number of segments to cache (uses config if None)
            prebuffer_segments (int): Number of segments to pre-buffer ahead (uses config if None)
        """
        from collections import OrderedDict
        import time
        from urllib.parse import urljoin
        self.max_cache_size = max_cache_size or settings.hls_prebuffer_cache_size
        self.prebuffer_segments = prebuffer_segments or settings.hls_prebuffer_segments
        self.max_memory_percent = settings.hls_prebuffer_max_memory_percent
        self.emergency_threshold = settings.hls_prebuffer_emergency_threshold
        # Cache LRU
        self.segment_cache: "OrderedDict[str, bytes]" = OrderedDict()
        # Mappa playlist -> lista segmenti
        self.segment_urls: Dict[str, List[str]] = {}
        # Mappa inversa segmento -> (playlist_url, index)
        self.segment_to_playlist: Dict[str, tuple[str, int]] = {}
        # Stato per playlist: {headers, last_access, refresh_task, target_duration}
        self.playlist_state: Dict[str, dict] = {}
        self.client = get_httpx_client()
        
    async def prebuffer_playlist(self, playlist_url: str, headers: Dict[str, str]) -> None:
        """
        Pre-buffer segments from an HLS playlist.
        
        Args:
            playlist_url (str): URL of the HLS playlist
            headers (Dict[str, str]): Headers to use for requests
        """
        try:
            logger.debug(f"Starting pre-buffer for playlist: {playlist_url}")
            response = await self.client.get(playlist_url, headers=headers)
            response.raise_for_status()
            playlist_content = response.text

            # Se master playlist: prendi la prima variante (fix relativo)
            if "#EXT-X-STREAM-INF" in playlist_content:
                logger.debug(f"Master playlist detected, finding first variant")
                variant_urls = self._extract_variant_urls(playlist_content, playlist_url)
                if variant_urls:
                    first_variant_url = variant_urls[0]
                    logger.debug(f"Pre-buffering first variant: {first_variant_url}")
                    await self.prebuffer_playlist(first_variant_url, headers)
                else:
                    logger.warning("No variants found in master playlist")
                return

            # Media playlist: estrai segmenti, salva stato e lancia refresh loop
            segment_urls = self._extract_segment_urls(playlist_content, playlist_url)
            self.segment_urls[playlist_url] = segment_urls
            # aggiorna mappa inversa
            for idx, u in enumerate(segment_urls):
                self.segment_to_playlist[u] = (playlist_url, idx)

            # prebuffer iniziale
            await self._prebuffer_segments(segment_urls[:self.prebuffer_segments], headers)
            logger.info(f"Pre-buffered {min(self.prebuffer_segments, len(segment_urls))} segments for {playlist_url}")

            # setup refresh loop se non già attivo
            target_duration = self._parse_target_duration(playlist_content) or 6
            st = self.playlist_state.get(playlist_url, {})
            if not st.get("refresh_task") or st["refresh_task"].done():
                task = asyncio.create_task(self._refresh_playlist_loop(playlist_url, headers, target_duration))
                self.playlist_state[playlist_url] = {
                    "headers": headers,
                    "last_access": asyncio.get_event_loop().time(),
                    "refresh_task": task,
                    "target_duration": target_duration,
                }
        except Exception as e:
            logger.warning(f"Failed to pre-buffer playlist {playlist_url}: {e}")
    
    def _extract_segment_urls(self, playlist_content: str, base_url: str) -> List[str]:
        """
        Extract segment URLs from HLS playlist content.
        
        Args:
            playlist_content (str): Content of the HLS playlist
            base_url (str): Base URL for resolving relative URLs
            
        Returns:
            List[str]: List of segment URLs
        """
        segment_urls = []
        lines = playlist_content.split('\n')
        
        logger.debug(f"Analyzing playlist with {len(lines)} lines")
        
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                # Check if line contains a URL (http/https) or is a relative path
                if 'http://' in line or 'https://' in line:
                    segment_urls.append(line)
                    logger.debug(f"Found absolute URL: {line}")
                elif line and not line.startswith('#'):
                    # This might be a relative path to a segment
                    parsed_base = urlparse(base_url)
                    # Ensure proper path joining
                    if line.startswith('/'):
                        segment_url = f"{parsed_base.scheme}://{parsed_base.netloc}{line}"
                    else:
                        # Get the directory path from base_url
                        base_path = parsed_base.path.rsplit('/', 1)[0] if '/' in parsed_base.path else ''
                        segment_url = f"{parsed_base.scheme}://{parsed_base.netloc}{base_path}/{line}"
                    segment_urls.append(segment_url)
                    logger.debug(f"Found relative path: {line} -> {segment_url}")
        
        logger.debug(f"Extracted {len(segment_urls)} segment URLs from playlist")
        if segment_urls:
            logger.debug(f"First segment URL: {segment_urls[0]}")
        else:
            logger.debug("No segment URLs found in playlist")
            # Log first few lines for debugging
            for i, line in enumerate(lines[:10]):
                logger.debug(f"Line {i}: {line}")
        
        return segment_urls
    
    def _extract_variant_urls(self, playlist_content: str, base_url: str) -> List[str]:
        """
        Estrae le varianti dal master playlist. Corretto per gestire URI relativi:
        prende la riga non-commento successiva a #EXT-X-STREAM-INF e la risolve rispetto a base_url.
        """
        from urllib.parse import urljoin
        variant_urls = []
        lines = [l.strip() for l in playlist_content.split('\n')]
        take_next_uri = False
        for line in lines:
            if line.startswith("#EXT-X-STREAM-INF"):
                take_next_uri = True
                continue
            if take_next_uri:
                take_next_uri = False
                if line and not line.startswith('#'):
                    variant_urls.append(urljoin(base_url, line))
        logger.debug(f"Extracted {len(variant_urls)} variant URLs from master playlist")
        if variant_urls:
            logger.debug(f"First variant URL: {variant_urls[0]}")
        return variant_urls
    
    async def _prebuffer_segments(self, segment_urls: List[str], headers: Dict[str, str]) -> None:
        """
        Pre-buffer specific segments.
        
        Args:
            segment_urls (List[str]): List of segment URLs to pre-buffer
            headers (Dict[str, str]): Headers to use for requests
        """
        tasks = []
        for url in segment_urls:
            if url not in self.segment_cache:
                tasks.append(self._download_segment(url, headers))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
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
        Esegue cleanup LRU rimuovendo il 50% più vecchio.
        """
        if self._check_memory_threshold():
            logger.warning("Emergency cache cleanup triggered due to high memory usage")
            to_remove = max(1, len(self.segment_cache) // 2)
            removed = 0
            while removed < to_remove and self.segment_cache:
                self.segment_cache.popitem(last=False)  # rimuovi LRU
                removed += 1
            logger.info(f"Emergency cleanup removed {removed} segments from cache")
    
    async def _download_segment(self, segment_url: str, headers: Dict[str, str]) -> None:
        """
        Download a single segment and cache it.
        
        Args:
            segment_url (str): URL of the segment to download
            headers (Dict[str, str]): Headers to use for request
        """
        try:
            memory_percent = self._get_memory_usage_percent()
            if memory_percent > self.max_memory_percent:
                logger.warning(f"Memory usage {memory_percent}% exceeds limit {self.max_memory_percent}%, skipping download")
                return

            response = await self.client.get(segment_url, headers=headers)
            response.raise_for_status()

            # Cache LRU
            self.segment_cache[segment_url] = response.content
            self.segment_cache.move_to_end(segment_url, last=True)

            if self._check_memory_threshold():
                self._emergency_cache_cleanup()
            elif len(self.segment_cache) > self.max_cache_size:
                # Evict LRU finché non rientra
                while len(self.segment_cache) > self.max_cache_size:
                    self.segment_cache.popitem(last=False)

            logger.debug(f"Cached segment: {segment_url}")
        except Exception as e:
            logger.warning(f"Failed to download segment {segment_url}: {e}")
    
    async def get_segment(self, segment_url: str, headers: Dict[str, str]) -> Optional[bytes]:
        """
        Get a segment from cache or download it.
        
        Args:
            segment_url (str): URL of the segment
            headers (Dict[str, str]): Headers to use for request
            
        Returns:
            Optional[bytes]: Cached segment data or None if not available
        """
        # Check cache first
        if segment_url in self.segment_cache:
            logger.debug(f"Cache hit for segment: {segment_url}")
            # LRU touch
            data = self.segment_cache[segment_url]
            self.segment_cache.move_to_end(segment_url, last=True)
            # aggiorna last_access per la playlist se mappata
            pl = self.segment_to_playlist.get(segment_url)
            if pl:
                st = self.playlist_state.get(pl[0])
                if st:
                    st["last_access"] = asyncio.get_event_loop().time()
            return data

        memory_percent = self._get_memory_usage_percent()
        if memory_percent > self.max_memory_percent:
            logger.warning(f"Memory usage {memory_percent}% exceeds limit {self.max_memory_percent}%, skipping download")
            return None

        try:
            response = await self.client.get(segment_url, headers=headers)
            response.raise_for_status()
            segment_data = response.content

            # Cache LRU
            self.segment_cache[segment_url] = segment_data
            self.segment_cache.move_to_end(segment_url, last=True)

            if self._check_memory_threshold():
                self._emergency_cache_cleanup()
            elif len(self.segment_cache) > self.max_cache_size:
                while len(self.segment_cache) > self.max_cache_size:
                    self.segment_cache.popitem(last=False)

            # aggiorna last_access per playlist
            pl = self.segment_to_playlist.get(segment_url)
            if pl:
                st = self.playlist_state.get(pl[0])
                if st:
                    st["last_access"] = asyncio.get_event_loop().time()

            logger.debug(f"Downloaded and cached segment: {segment_url}")
            return segment_data
        except Exception as e:
            logger.warning(f"Failed to get segment {segment_url}: {e}")
            return None
    
    async def prebuffer_from_segment(self, segment_url: str, headers: Dict[str, str]) -> None:
        """
        Dato un URL di segmento, prebuffer i successivi in base alla playlist e all'indice mappato.
        """
        mapped = self.segment_to_playlist.get(segment_url)
        if not mapped:
            return
        playlist_url, idx = mapped
        # aggiorna access time
        st = self.playlist_state.get(playlist_url)
        if st:
            st["last_access"] = asyncio.get_event_loop().time()
        await self.prebuffer_next_segments(playlist_url, idx, headers)
    
    async def prebuffer_next_segments(self, playlist_url: str, current_segment_index: int, headers: Dict[str, str]) -> None:
        """
        Pre-buffer next segments based on current playback position.
        
        Args:
            playlist_url (str): URL of the playlist
            current_segment_index (int): Index of current segment
            headers (Dict[str, str]): Headers to use for requests
        """
        if playlist_url not in self.segment_urls:
            return
        segment_urls = self.segment_urls[playlist_url]
        next_segments = segment_urls[current_segment_index + 1:current_segment_index + 1 + self.prebuffer_segments]
        if next_segments:
            await self._prebuffer_segments(next_segments, headers)
    
    def clear_cache(self) -> None:
        """Clear the segment cache."""
        self.segment_cache.clear()
        self.segment_urls.clear()
        self.segment_to_playlist.clear()
        self.playlist_state.clear()
        logger.info("HLS pre-buffer cache cleared")
    
    async def close(self) -> None:
        """Close the pre-buffer system."""
        # Do not close the shared client
        pass


# Global pre-buffer instance
hls_prebuffer = HLSPreBuffer()


class HLSPreBuffer:
    def _parse_target_duration(self, playlist_content: str) -> Optional[int]:
        """
        Parse EXT-X-TARGETDURATION from a media playlist and return duration in seconds.
        Returns None if not present or unparsable.
        """
        for line in playlist_content.splitlines():
            line = line.strip()
            if line.startswith("#EXT-X-TARGETDURATION:"):
                try:
                    value = line.split(":", 1)[1].strip()
                    return int(float(value))
                except Exception:
                    return None
        return None
    
    async def _refresh_playlist_loop(self, playlist_url: str, headers: Dict[str, str], target_duration: int) -> None:
        """
        Aggiorna periodicamente la playlist per seguire la sliding window e mantenere la cache coerente.
        Interrompe e pulisce dopo inattività prolungata.
        """
        sleep_s = max(2, min(15, int(target_duration)))
        inactivity_timeout = 600  # 10 minuti
        while True:
            try:
                st = self.playlist_state.get(playlist_url)
                now = asyncio.get_event_loop().time()
                if not st:
                    return
                if now - st.get("last_access", now) > inactivity_timeout:
                    # cleanup specifico della playlist
                    urls = set(self.segment_urls.get(playlist_url, []))
                    if urls:
                        # rimuovi dalla cache solo i segmenti di questa playlist
                        for u in list(self.segment_cache.keys()):
                            if u in urls:
                                self.segment_cache.pop(u, None)
                        # rimuovi mapping
                        for u in urls:
                            self.segment_to_playlist.pop(u, None)
                    self.segment_urls.pop(playlist_url, None)
                    self.playlist_state.pop(playlist_url, None)
                    logger.info(f"Stopped HLS prebuffer for inactive playlist: {playlist_url}")
                    return

                # refresh manifest
                resp = await self.client.get(playlist_url, headers=headers)
                resp.raise_for_status()
                content = resp.text
                new_target = self._parse_target_duration(content)
                if new_target:
                    sleep_s = max(2, min(15, int(new_target)))

                new_urls = self._extract_segment_urls(content, playlist_url)
                if new_urls:
                    self.segment_urls[playlist_url] = new_urls
                    # rebuild reverse map per gli ultimi N (limita la memoria)
                    for idx, u in enumerate(new_urls[-(self.max_cache_size * 2):]):
                        # rimappiando sovrascrivi eventuali entry
                        real_idx = len(new_urls) - (self.max_cache_size * 2) + idx if len(new_urls) > (self.max_cache_size * 2) else idx
                        self.segment_to_playlist[u] = (playlist_url, real_idx)

                # tenta un prebuffer proattivo: se conosciamo l'ultimo segmento accessibile, anticipa i successivi
                # Non conosciamo l'indice di riproduzione corrente qui, quindi non facciamo nulla di aggressivo.

            except Exception as e:
                logger.debug(f"Playlist refresh error for {playlist_url}: {e}")
            await asyncio.sleep(sleep_s)
    def _extract_segment_urls(self, playlist_content: str, base_url: str) -> List[str]:
        """
        Extract segment URLs from HLS playlist content.
        
        Args:
            playlist_content (str): Content of the HLS playlist
            base_url (str): Base URL for resolving relative URLs
            
        Returns:
            List[str]: List of segment URLs
        """
        segment_urls = []
        lines = playlist_content.split('\n')
        
        logger.debug(f"Analyzing playlist with {len(lines)} lines")
        
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                # Check if line contains a URL (http/https) or is a relative path
                if 'http://' in line or 'https://' in line:
                    segment_urls.append(line)
                    logger.debug(f"Found absolute URL: {line}")
                elif line and not line.startswith('#'):
                    # This might be a relative path to a segment
                    parsed_base = urlparse(base_url)
                    # Ensure proper path joining
                    if line.startswith('/'):
                        segment_url = f"{parsed_base.scheme}://{parsed_base.netloc}{line}"
                    else:
                        # Get the directory path from base_url
                        base_path = parsed_base.path.rsplit('/', 1)[0] if '/' in parsed_base.path else ''
                        segment_url = f"{parsed_base.scheme}://{parsed_base.netloc}{base_path}/{line}"
                    segment_urls.append(segment_url)
                    logger.debug(f"Found relative path: {line} -> {segment_url}")
        
        logger.debug(f"Extracted {len(segment_urls)} segment URLs from playlist")
        if segment_urls:
            logger.debug(f"First segment URL: {segment_urls[0]}")
        else:
            logger.debug("No segment URLs found in playlist")
            # Log first few lines for debugging
            for i, line in enumerate(lines[:10]):
                logger.debug(f"Line {i}: {line}")
        
        return segment_urls
    
    def _extract_variant_urls(self, playlist_content: str, base_url: str) -> List[str]:
        """
        Estrae le varianti dal master playlist. Corretto per gestire URI relativi:
        prende la riga non-commento successiva a #EXT-X-STREAM-INF e la risolve rispetto a base_url.
        """
        from urllib.parse import urljoin
        variant_urls = []
        lines = [l.strip() for l in playlist_content.split('\n')]
        take_next_uri = False
        for line in lines:
            if line.startswith("#EXT-X-STREAM-INF"):
                take_next_uri = True
                continue
            if take_next_uri:
                take_next_uri = False
                if line and not line.startswith('#'):
                    variant_urls.append(urljoin(base_url, line))
        logger.debug(f"Extracted {len(variant_urls)} variant URLs from master playlist")
        if variant_urls:
            logger.debug(f"First variant URL: {variant_urls[0]}")
        return variant_urls
=======
"""
HLS Pre-buffer system with priority-based sequential prefetching.

This module provides a smart prebuffering system that:
- Prioritizes player-requested segments (downloaded immediately)
- Prefetches remaining segments sequentially in background
- Supports multiple users watching the same channel (shared prefetcher)
- Cleans up inactive prefetchers automatically

Architecture:
1. When playlist is fetched, register_playlist() creates a PlaylistPrefetcher
2. PlaylistPrefetcher runs a background loop: priority queue -> sequential prefetch
3. When player requests a segment, request_segment() adds it to priority queue
4. Prefetcher downloads priority segment first, then continues sequential
"""

import asyncio
import logging
import time
from typing import Dict, Optional, List
from urllib.parse import urljoin

from mediaflow_proxy.utils.base_prebuffer import BasePrebuffer
from mediaflow_proxy.utils.cache_utils import get_cached_segment
from mediaflow_proxy.configs import settings

logger = logging.getLogger(__name__)


class PlaylistPrefetcher:
    """
    Manages prefetching for a single playlist with priority support.

    Key design for live streams with changing tokens:
    - Does NOT start prefetching immediately on registration
    - Only starts prefetching AFTER player requests a segment
    - This ensures we prefetch from the CURRENT playlist, not stale ones

    The prefetcher runs a background loop that:
    1. Waits for player to request a segment (priority)
    2. Downloads the priority segment first
    3. Then prefetches subsequent segments sequentially
    4. Stops when cancelled or all segments are prefetched
    """

    def __init__(
        self,
        playlist_url: str,
        segment_urls: List[str],
        headers: Dict[str, str],
        prebuffer: "HLSPreBuffer",
        prefetch_limit: int = 5,
    ):
        """
        Initialize a playlist prefetcher.

        Args:
            playlist_url: URL of the HLS playlist
            segment_urls: Ordered list of segment URLs from the playlist
            headers: Headers to use for requests
            prebuffer: Parent HLSPreBuffer instance for download methods
            prefetch_limit: Maximum number of segments to prefetch ahead of player position
        """
        self.playlist_url = playlist_url
        self.segment_urls = segment_urls
        self.headers = headers
        self.prebuffer = prebuffer
        self.prefetch_limit = prefetch_limit

        self.last_access = time.time()
        self.current_index = 0  # Next segment to prefetch sequentially
        self.player_index = 0  # Last segment index requested by player
        self.priority_event = asyncio.Event()  # Signals priority segment available
        self.priority_url: Optional[str] = None  # Current priority segment
        self.cancelled = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()  # Protects priority_url

        # Track which segments are already cached or being downloaded
        self.downloading: set = set()

        # Track if prefetching has been activated by a player request
        self.activated = False

    def start(self) -> None:
        """Start the prefetch background task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
            logger.info(f"[PlaylistPrefetcher] Started (waiting for activation): {self.playlist_url}")

    def stop(self) -> None:
        """Stop the prefetch background task."""
        self.cancelled = True
        self.priority_event.set()  # Wake up the loop
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info(f"[PlaylistPrefetcher] Stopped for: {self.playlist_url}")

    def update_segments(self, segment_urls: List[str]) -> None:
        """
        Update segment URLs (called when playlist is refreshed).

        Args:
            segment_urls: New list of segment URLs
        """
        self.segment_urls = segment_urls
        self.last_access = time.time()
        logger.debug(f"[PlaylistPrefetcher] Updated segments ({len(segment_urls)}): {self.playlist_url}")

    async def request_priority(self, segment_url: str) -> None:
        """
        Player requested this segment - update indices and activate prefetching.

        The player will download this segment via get_or_download().
        The prefetcher's job is to prefetch segments AHEAD of the player,
        not to download the segment the player is already requesting.

        For VOD/movie streams: handles seek by detecting large jumps in segment
        index and resetting the prefetch window accordingly.

        Args:
            segment_url: URL of the segment the player needs
        """
        self.last_access = time.time()
        self.activated = True  # Activate prefetching

        # Update player position for prefetch limit calculation
        segment_index = self._find_segment_index(segment_url)
        if segment_index >= 0:
            old_player_index = self.player_index
            self.player_index = segment_index
            # Start prefetching from the NEXT segment (player handles current one)
            self.current_index = segment_index + 1

            # Detect seek: if player jumped more than prefetch_limit segments
            # This handles VOD seek scenarios where user jumps to different position
            jump_distance = abs(segment_index - old_player_index)
            if jump_distance > self.prefetch_limit and old_player_index >= 0:
                logger.info(
                    f"[PlaylistPrefetcher] Seek detected: jumped {jump_distance} segments "
                    f"(from {old_player_index} to {segment_index})"
                )

        # Signal the prefetch loop to wake up and start prefetching ahead
        async with self._lock:
            self.priority_url = segment_url
            self.priority_event.set()

    def _find_segment_index(self, segment_url: str) -> int:
        """Find the index of a segment URL in the list."""
        try:
            return self.segment_urls.index(segment_url)
        except ValueError:
            return -1

    async def _run(self) -> None:
        """
        Main prefetch loop.

        For live streams: waits until activated by player request before prefetching.
        Priority: Player-requested segment > Sequential prefetch
        After downloading priority segment, continue sequential from that point.

        Prefetching is LIMITED to `prefetch_limit` segments ahead of the player's
        current position to avoid downloading the entire stream.
        """
        logger.info(f"[PlaylistPrefetcher] Loop started for: {self.playlist_url}")

        while not self.cancelled:
            try:
                # Wait for activation (player request) before doing anything
                if not self.activated:
                    try:
                        await asyncio.wait_for(self.priority_event.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue

                # Check for priority segment first
                async with self._lock:
                    priority_url = self.priority_url
                    self.priority_url = None
                    self.priority_event.clear()

                if priority_url:
                    # Player is already downloading this segment via get_or_download()
                    # We just need to update our indices and skip to prefetching NEXT segments
                    # This avoids duplicate download attempts and inflated cache miss stats
                    priority_index = self._find_segment_index(priority_url)
                    if priority_index >= 0:
                        self.player_index = priority_index
                        self.current_index = priority_index + 1  # Start prefetching from next segment
                        logger.info(
                            f"[PlaylistPrefetcher] Player at index {self.player_index}, "
                            f"will prefetch up to {self.prefetch_limit} segments ahead"
                        )
                    continue

                # Calculate prefetch limit based on player position
                max_prefetch_index = self.player_index + self.prefetch_limit + 1

                # No priority - prefetch next sequential segment (only if within limit)
                if (
                    self.activated
                    and self.current_index < len(self.segment_urls)
                    and self.current_index < max_prefetch_index
                ):
                    url = self.segment_urls[self.current_index]

                    # Skip if already cached or being downloaded
                    if url not in self.downloading:
                        cached = await get_cached_segment(url)
                        if not cached:
                            logger.info(
                                f"[PlaylistPrefetcher] Prefetching [{self.current_index}] "
                                f"(player at {self.player_index}, limit {self.prefetch_limit}): {url}"
                            )
                            await self._download_segment(url)
                        else:
                            logger.debug(f"[PlaylistPrefetcher] Already cached [{self.current_index}]: {url}")

                    self.current_index += 1
                else:
                    # Reached prefetch limit or end of segments - wait for player to advance
                    try:
                        await asyncio.wait_for(self.priority_event.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        pass

            except asyncio.CancelledError:
                logger.info(f"[PlaylistPrefetcher] Loop cancelled: {self.playlist_url}")
                return
            except Exception as e:
                logger.warning(f"[PlaylistPrefetcher] Error in loop: {e}")
                await asyncio.sleep(0.5)

        logger.info(f"[PlaylistPrefetcher] Loop ended: {self.playlist_url}")

    async def _download_segment(self, url: str) -> None:
        """
        Download and cache a segment using the parent prebuffer.

        Args:
            url: URL of the segment to download
        """
        if url in self.downloading:
            return

        self.downloading.add(url)
        try:
            # Use the base prebuffer's get_or_download for cross-process coordination
            await self.prebuffer.get_or_download(url, self.headers)
        finally:
            self.downloading.discard(url)


class HLSPreBuffer(BasePrebuffer):
    """
    Pre-buffer system for HLS streams with priority-based prefetching.

    Features:
    - Priority queue: Player-requested segments downloaded first
    - Sequential prefetch: Background prefetch of remaining segments
    - Multi-user support: Multiple users share same prefetcher
    - Automatic cleanup: Inactive prefetchers removed after timeout
    """

    def __init__(
        self,
        max_cache_size: Optional[int] = None,
        prebuffer_segments: Optional[int] = None,
    ):
        """
        Initialize the HLS pre-buffer system.

        Args:
            max_cache_size: Maximum number of segments to cache (uses config if None)
            prebuffer_segments: Number of segments to pre-buffer ahead (uses config if None)
        """
        super().__init__(
            max_cache_size=max_cache_size or settings.hls_prebuffer_cache_size,
            prebuffer_segments=prebuffer_segments or settings.hls_prebuffer_segments,
            max_memory_percent=settings.hls_prebuffer_max_memory_percent,
            emergency_threshold=settings.hls_prebuffer_emergency_threshold,
            segment_ttl=settings.hls_segment_cache_ttl,
        )

        self.inactivity_timeout = settings.hls_prebuffer_inactivity_timeout

        # Active prefetchers: playlist_url -> PlaylistPrefetcher
        self.active_prefetchers: Dict[str, PlaylistPrefetcher] = {}

        # Reverse mapping: segment URL -> playlist_url
        self.segment_to_playlist: Dict[str, str] = {}

        # Lock for prefetcher management
        self._prefetcher_lock = asyncio.Lock()

        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_interval = 30  # Check every 30 seconds

    def log_stats(self) -> None:
        """Log current prebuffer statistics with HLS-specific info."""
        stats = self.stats.to_dict()
        stats["active_prefetchers"] = len(self.active_prefetchers)
        logger.info(f"HLS Prebuffer Stats: {stats}")

    def _extract_segment_urls(self, playlist_content: str, base_url: str) -> List[str]:
        """
        Extract segment URLs from HLS playlist content.

        Args:
            playlist_content: Content of the HLS playlist
            base_url: Base URL for resolving relative URLs

        Returns:
            List of segment URLs
        """
        segment_urls = []
        lines = playlist_content.split("\n")

        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                # Absolute URL
                if line.startswith("http://") or line.startswith("https://"):
                    segment_urls.append(line)
                else:
                    # Relative URL - resolve against base
                    segment_url = urljoin(base_url, line)
                    segment_urls.append(segment_url)

        return segment_urls

    def _is_master_playlist(self, playlist_content: str) -> bool:
        """Check if this is a master playlist (contains variant streams)."""
        return "#EXT-X-STREAM-INF" in playlist_content

    async def register_playlist(
        self,
        playlist_url: str,
        segment_urls: List[str],
        headers: Dict[str, str],
    ) -> None:
        """
        Register a playlist for prefetching.

        Creates a new PlaylistPrefetcher or updates existing one.
        Called by M3U8 processor when a playlist is fetched.

        Args:
            playlist_url: URL of the HLS playlist
            segment_urls: Ordered list of segment URLs from the playlist
            headers: Headers to use for requests
        """
        if not segment_urls:
            logger.debug(f"[register_playlist] No segments, skipping: {playlist_url}")
            return

        async with self._prefetcher_lock:
            # Update reverse mapping
            for url in segment_urls:
                self.segment_to_playlist[url] = playlist_url

            if playlist_url in self.active_prefetchers:
                # Update existing prefetcher
                prefetcher = self.active_prefetchers[playlist_url]
                prefetcher.update_segments(segment_urls)
                prefetcher.headers = headers
                logger.info(f"[register_playlist] Updated existing prefetcher: {playlist_url}")
            else:
                # Create new prefetcher with configured prefetch limit
                prefetcher = PlaylistPrefetcher(
                    playlist_url=playlist_url,
                    segment_urls=segment_urls,
                    headers=headers,
                    prebuffer=self,
                    prefetch_limit=settings.hls_prebuffer_segments,
                )
                self.active_prefetchers[playlist_url] = prefetcher
                prefetcher.start()
                logger.info(
                    f"[register_playlist] Created new prefetcher ({len(segment_urls)} segments, "
                    f"prefetch_limit={settings.hls_prebuffer_segments}): {playlist_url}"
                )

            # Ensure cleanup task is running
            self._ensure_cleanup_task()

    async def request_segment(self, segment_url: str) -> None:
        """
        Player requested a segment - set as priority for prefetching.

        Finds the prefetcher for this segment and adds it to priority queue.
        Called by the segment endpoint when a segment is requested.

        Args:
            segment_url: URL of the segment the player needs
        """
        playlist_url = self.segment_to_playlist.get(segment_url)
        if not playlist_url:
            logger.debug(f"[request_segment] No prefetcher found for: {segment_url}")
            return

        prefetcher = self.active_prefetchers.get(playlist_url)
        if prefetcher:
            await prefetcher.request_priority(segment_url)
        else:
            logger.debug(f"[request_segment] Prefetcher not active for: {playlist_url}")

    def _ensure_cleanup_task(self) -> None:
        """Ensure the cleanup task is running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """Periodically clean up inactive prefetchers."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_inactive_prefetchers()
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"[cleanup_loop] Error: {e}")

    async def _cleanup_inactive_prefetchers(self) -> None:
        """Remove prefetchers that haven't been accessed recently."""
        now = time.time()
        to_remove = []

        async with self._prefetcher_lock:
            for playlist_url, prefetcher in self.active_prefetchers.items():
                inactive_time = now - prefetcher.last_access
                if inactive_time > self.inactivity_timeout:
                    to_remove.append(playlist_url)
                    logger.info(f"[cleanup] Removing inactive prefetcher ({inactive_time:.0f}s): {playlist_url}")

            for playlist_url in to_remove:
                prefetcher = self.active_prefetchers.pop(playlist_url, None)
                if prefetcher:
                    prefetcher.stop()
                    # Clean up reverse mapping
                    for url in prefetcher.segment_urls:
                        self.segment_to_playlist.pop(url, None)

        if to_remove:
            logger.info(f"[cleanup] Removed {len(to_remove)} inactive prefetchers")

    def get_stats(self) -> dict:
        """Get current prebuffer statistics."""
        stats = self.stats.to_dict()
        stats["active_prefetchers"] = len(self.active_prefetchers)
        return stats

    def clear_cache(self) -> None:
        """Clear all prebuffer state and log final stats."""
        self.log_stats()

        # Stop all prefetchers
        for prefetcher in self.active_prefetchers.values():
            prefetcher.stop()

        self.active_prefetchers.clear()
        self.segment_to_playlist.clear()
        self.stats.reset()

        logger.info("HLS pre-buffer state cleared")

    async def close(self) -> None:
        """Close the pre-buffer system."""
        self.clear_cache()
        if self._cleanup_task:
            self._cleanup_task.cancel()


# Global HLS pre-buffer instance
hls_prebuffer = HLSPreBuffer()
>>>>>>> upstream/main
