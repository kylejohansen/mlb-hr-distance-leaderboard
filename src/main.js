import './styles.css';

const DATA_URL = '/data/hr-distance-latest.json';
const HOT_DOG_URL = '/data/hot-dog-stand-latest.json';
const DAILY_DONG_OVERRIDES_URL = '/data/daily-dong-overrides.json';
const POSTS_URL = '/data/posts.json';
const CURRENT_SEASON = 2026;
const LBI_SEASONS = [2026, 2025, 2024, 2023, 2022, 2021];

const columns = [
  { key: 'rank', label: '#', numeric: true },
  { key: 'player', label: 'Player' },
  { key: 'team', label: 'Team' },
  { key: 'longballIndex', label: 'LBI', numeric: true },
  { key: 'bbe', label: 'BBE', numeric: true },
  { key: 'hr', label: 'HR', numeric: true },
  { key: 'xhrPerBbe', label: 'xHR/BBE', numeric: true, unit: 'percent' },
  { key: 'barrelRate', label: 'Barrel%', shortLabel: 'Brl%', numeric: true, unit: 'percent' },
  { key: 'hardHitRate', label: 'Hard Hit%', shortLabel: 'HH%', numeric: true, unit: 'percent' },
  { key: 'avgDistanceOnBarrels', label: 'Avg Barrel Dist.', shortLabel: 'Avg Brl Dist', numeric: true, unit: 'ft' },
  { key: 'pullAirRate', label: 'PULLAIR%', shortLabel: 'PULLAIR%', numeric: true, unit: 'percent' },
  { key: 'sweetSpotRate', label: 'SwSp% (REF)', numeric: true, unit: 'percent' }
];

const hotDogColumns = [
  { key: 'rank', label: '#', numeric: true },
  { key: 'pitcher', label: 'Pitcher' },
  { key: 'team', label: 'Team' },
  { key: 'pitcherRole', label: 'Role' },
  { key: 'hotDogIndex', label: 'Hot Dog Index', shortLabel: 'HDI', numeric: true, unit: 'lbi' },
  { key: 'cookedPer100Bbe', label: 'Cooked / 100 BBE', shortLabel: 'Cooked/100', numeric: true, unit: 'lbi' },
  { key: 'totalBbeAllowed', label: 'BBE Allowed', shortLabel: 'BBE', numeric: true },
  { key: 'hrCapableBbeAllowed', label: 'HR-Capable BBE', shortLabel: 'HR-Cap', numeric: true },
  { key: 'noDoubtersAllowed', label: 'No-Doubters', shortLabel: 'ND', numeric: true },
  { key: 'mostlyGoneAllowed', label: 'Mostly Gone', shortLabel: 'MG', numeric: true },
  { key: 'doubtersAllowed', label: 'Doubters', shortLabel: 'Doubters', numeric: true },
  { key: 'avgExitVelocityAllowed', label: 'Avg EV / HR', shortLabel: 'Avg EV/HR', numeric: true, unit: 'mph' },
  { key: 'avgDistanceAllowed', label: 'Avg HR Dist', shortLabel: 'Avg HR Dist', numeric: true, unit: 'ft' },
  { key: 'maxDistanceAllowed', label: 'Longest HR', shortLabel: 'Longest HR', numeric: true, unit: 'ft' },
  { key: 'maxExitVelocityAllowed', label: 'Hardest Hit', shortLabel: 'Hardest', numeric: true, unit: 'mph' }
];

const ROUTES = {
  home: '/',
  hotDog: '/hot-dog-stand',
  notes: '/notes',
  reports: '/reports/latest-longball-scouting-report',
  stackWatch: '/stack-watch',
  about: '/about'
};

function getRouteState() {
  const { pathname, hash } = window.location;

  if (hash.startsWith('#about')) {
    return { view: 'about', aboutAnchor: hash.split('/')[1] ?? '', postSlug: '' };
  }

  if (hash.startsWith('#notes')) {
    return { view: 'notes', aboutAnchor: '', postSlug: hash.startsWith('#notes/') ? hash.slice('#notes/'.length) : '' };
  }

  if (hash === '#hot-dog') {
    return { view: 'hot-dog', aboutAnchor: '', postSlug: '' };
  }

  if (pathname === ROUTES.hotDog) return { view: 'hot-dog', aboutAnchor: '', postSlug: '' };
  if (pathname === ROUTES.about || pathname.startsWith(`${ROUTES.about}/`)) {
    return { view: 'about', aboutAnchor: pathname.slice(`${ROUTES.about}/`.length), postSlug: '' };
  }
  if (pathname === ROUTES.notes || pathname.startsWith(`${ROUTES.notes}/`)) {
    return { view: 'notes', aboutAnchor: '', postSlug: pathname.slice(`${ROUTES.notes}/`.length) };
  }

  return { view: 'home', aboutAnchor: '', postSlug: '' };
}

function getViewFromLocation() {
  return getRouteState().view;
}

function navigateTo(url) {
  window.history.pushState({}, '', url);
  state.view = getViewFromLocation();
  state.selectedPlayerId = null;
  state.selectedPitcherId = null;
  render();
}

function handleInternalNavigation(event) {
  const link = event.target.closest('a[href]');
  if (!link) return;

  const url = new URL(link.href, window.location.origin);
  if (url.origin !== window.location.origin) return;
  if (!url.pathname.startsWith('/') || url.pathname.includes('.')) return;
  if (url.pathname === '/reports' || url.pathname.startsWith('/reports/')) return;
  if (url.pathname === ROUTES.stackWatch) return;

  event.preventDefault();
  navigateTo(`${url.pathname}${url.hash}`);
}

function getAboutAnchor() {
  return getRouteState().aboutAnchor;
}

function getSelectedPostSlugFromLocation() {
  return getRouteState().postSlug;
}

function getPostUrl(slug) {
  return `${ROUTES.notes}/${slug}`;
}

function getConceptUrl(anchor) {
  return `${ROUTES.about}/${anchor}`;
}

const state = {
  rows: [],
  generatedAt: '',
  dailyDong: null,
  dailyFeatures: null,
  dailyDongOverrides: {},
  query: '',
  minHr: 1,
  sortKey: 'longballIndex',
  sortDirection: 'desc',
  status: 'loading',
  error: '',
  selectedSeason: CURRENT_SEASON,
  selectedPlayerId: null,
  selectedPitcherId: null,
  hotDogPitchers: [],
  hotDogGeneratedAt: '',
  hotDogStatus: 'loading',
  hotDogError: '',
  hotDogQuery: '',
  hotDogMinHrCapable: 5,
  hotDogRole: 'all',
  hotDogSortKey: 'hotDogIndex',
  hotDogSortDirection: 'desc',
  posts: [],
  postsStatus: 'loading',
  postsError: '',
  view: getViewFromLocation()
};

const app = document.querySelector('#app');

function normalizeRow(row, index) {
  return {
    batter: Number(row.batter ?? row.batter_id ?? 0),
    player: String(row.player ?? row.player_name ?? '').trim(),
    team: String(row.team ?? '').trim(),
    position: String(row.position ?? row.primaryPosition ?? row.pos ?? '').trim(),
    bbe: Number(row.bbe ?? 0),
    pa: Number(row.pa ?? row.plateAppearances ?? 0),
    hr: Number(row.hr ?? row.home_runs ?? row.homeRuns),
    avgDistance: Number(row.avgDistance ?? row.avg_hr_distance ?? row.avg_distance),
    longestHr: Number(row.longestHr ?? row.longest_hr ?? row.max_distance),
    avgExitVelocity: Number(row.avgExitVelocity ?? row.avg_exit_velocity ?? row.avg_ev),
    xhr: row.xhr == null ? null : Number(row.xhr),
    xhrPerBbe: row.xhrPerBbe == null ? null : Number(row.xhrPerBbe),
    xhrDiff: row.xhrDiff == null ? null : Number(row.xhrDiff),
    noDoubters: row.noDoubters == null ? null : Number(row.noDoubters),
    doubters: row.doubters == null ? null : Number(row.doubters),
    mostlyGone: row.mostlyGone == null ? null : Number(row.mostlyGone),
    actualDoubterHr: row.actualDoubterHr == null ? null : Number(row.actualDoubterHr),
    actualMostlyGoneHr: row.actualMostlyGoneHr == null ? null : Number(row.actualMostlyGoneHr),
    actualNoDoubterHr: row.actualNoDoubterHr == null ? null : Number(row.actualNoDoubterHr),
    noDoubterRate: row.noDoubterRate == null ? null : Number(row.noDoubterRate),
    barrelRate: Number(row.barrelRate ?? 0),
    hrWindowThunderRate: row.hrWindowThunderRate == null ? null : Number(row.hrWindowThunderRate),
    hrWindowThunderBbe: row.hrWindowThunderBbe == null ? null : Number(row.hrWindowThunderBbe),
    hardHitRate: Number(row.hardHitRate ?? 0),
    avgDistanceOnBarrels: row.avgDistanceOnBarrels == null ? null : Number(row.avgDistanceOnBarrels),
    avgLaunchAngleOnBarrels: row.avgLaunchAngleOnBarrels == null ? null : Number(row.avgLaunchAngleOnBarrels),
    pullAirRate: row.pullAirRate == null ? null : Number(row.pullAirRate),
    pulledAirBbe: row.pulledAirBbe == null ? null : Number(row.pulledAirBbe),
    crushedPulledAirBbe: row.crushedPulledAirBbe == null ? null : Number(row.crushedPulledAirBbe),
    pullAirJuice: row.pullAirJuice == null ? null : Number(row.pullAirJuice),
    pullAirJuicePer100Pa: row.pullAirJuicePer100Pa == null ? null : Number(row.pullAirJuicePer100Pa),
    sweetSpotRate: Number(row.sweetSpotRate ?? 0),
    longballIndex: Number(row.longballIndex ?? 0),
    lbiVersion: String(row.lbiVersion ?? '1.3'),
    lbiComponents: row.lbiComponents ?? {},
    sampleBadge: String(row.sampleBadge ?? 'Building Sample'),
    sourceRank: index + 1
  };
}

function getRowsFromPayload(payload) {
  const rows = Array.isArray(payload) ? payload : payload?.players;

  if (!Array.isArray(rows)) {
    throw new Error('Expected the JSON to be an array or an object with a players array.');
  }

  return rows.map(normalizeRow).filter((row) => {
    return (
      row.player &&
      row.team &&
      Number.isFinite(row.bbe) &&
      Number.isFinite(row.hr) &&
      Number.isFinite(row.longballIndex)
    );
  });
}

function normalizeHotDogRow(row, index) {
  return {
    pitcherId: Number(row.pitcherId ?? row.pitcher_id ?? row.player_id ?? 0),
    pitcher: String(row.pitcher ?? row.pitcher_name ?? row.player_name ?? '').trim(),
    team: String(row.team ?? '').trim(),
    pitcherRole: String(row.pitcherRole ?? row.pitcher_role ?? '').trim(),
    appearances: Number(row.appearances ?? 0),
    gamesStarted: Number(row.gamesStarted ?? row.games_started ?? 0),
    reliefAppearances: Number(row.reliefAppearances ?? row.relief_appearances ?? 0),
    hotDogIndex: row.hotDogIndex == null ? null : Number(row.hotDogIndex),
    bbeAllowed: Number(row.bbeAllowed ?? row.bbe_allowed ?? 0),
    totalBbeAllowed: Number(row.totalBbeAllowed ?? row.total_bbe_allowed ?? row.bbeAllowed ?? row.bbe_allowed ?? 0),
    cookedPer100Bbe: row.cookedPer100Bbe == null ? null : Number(row.cookedPer100Bbe),
    hrsAllowed: Number(row.hrsAllowed ?? row.hrs_allowed ?? row.hr_total ?? 0),
    adjustedXhrAllowed: row.adjustedXhrAllowed == null ? null : Number(row.adjustedXhrAllowed),
    adjustedXhrPerBbeAllowed: row.adjustedXhrPerBbeAllowed == null ? null : Number(row.adjustedXhrPerBbeAllowed),
    xhrDiffAllowed: row.xhrDiffAllowed == null ? null : Number(row.xhrDiffAllowed),
    hrCapableBbeAllowed: Number(row.hrCapableBbeAllowed ?? row.hr_capable_bbe_allowed ?? 0),
    hrCapableBbeRateAllowed: row.hrCapableBbeRateAllowed == null ? null : Number(row.hrCapableBbeRateAllowed),
    hrWindowThunderBbeAllowed: Number(row.hrWindowThunderBbeAllowed ?? row.hr_window_thunder_bbe_allowed ?? 0),
    hrWindowThunderRateAllowed: row.hrWindowThunderRateAllowed == null ? null : Number(row.hrWindowThunderRateAllowed),
    noDoubtersAllowed: Number(row.noDoubtersAllowed ?? row.no_doubters_allowed ?? 0),
    mostlyGoneAllowed: Number(row.mostlyGoneAllowed ?? row.mostly_gone_allowed ?? 0),
    doubtersAllowed: Number(row.doubtersAllowed ?? row.doubters_allowed ?? 0),
    noDoubterRateAllowed: row.noDoubterRateAllowed == null ? null : Number(row.noDoubterRateAllowed),
    meatballPitchesThrown: Number(row.meatballPitchesThrown ?? row.meatball_pitches_thrown ?? 0),
    meatballHrs: Number(row.meatballHrs ?? row.meatball_hrs ?? row.meatballs_allowed ?? 0),
    meatballHitsAllowed: Number(row.meatballHitsAllowed ?? row.meatball_hits_allowed ?? 0),
    meatballAvgEvAllowed: row.meatballAvgEvAllowed == null ? null : Number(row.meatballAvgEvAllowed),
    luckyDogRate: row.luckyDogRate == null ? null : Number(row.luckyDogRate),
    avgExitVelocityAllowed: row.avgExitVelocityAllowed == null ? null : Number(row.avgExitVelocityAllowed),
    avgDistanceAllowed: row.avgDistanceAllowed == null ? null : Number(row.avgDistanceAllowed),
    maxExitVelocityAllowed: row.maxExitVelocityAllowed == null ? null : Number(row.maxExitVelocityAllowed),
    maxDistanceAllowed: row.maxDistanceAllowed == null ? null : Number(row.maxDistanceAllowed),
    avgLaunchAngleAllowed: row.avgLaunchAngleAllowed == null ? null : Number(row.avgLaunchAngleAllowed),
    stackWatchScore: row.stackWatchScore == null ? null : Number(row.stackWatchScore),
    stackWatchSampleTag: String(row.stackWatchSampleTag ?? row.sampleTag ?? '').trim(),
    opponentLineupAvgLbi: row.opponentLineupAvgLbi == null ? null : Number(row.opponentLineupAvgLbi),
    parkHrTag: String(row.parkHrTag ?? '').trim(),
    worstServedEvent: row.worstServedEvent ?? null,
    sourceRank: index + 1
  };
}

function getHotDogRowsFromPayload(payload) {
  const rows = Array.isArray(payload) ? payload : payload?.pitchers;

  if (!Array.isArray(rows)) {
    throw new Error('Expected the Hot Dog Stand JSON to be an array or an object with a pitchers array.');
  }

  return rows.map(normalizeHotDogRow).filter((row) => {
    return row.pitcher && Number.isFinite(row.hrsAllowed) && Number.isFinite(row.hotDogIndex);
  });
}

function normalizePost(post) {
  return {
    slug: String(post.slug ?? '').trim(),
    title: String(post.title ?? '').trim(),
    date: String(post.date ?? '').trim(),
    description: String(post.description ?? '').trim(),
    structuredData: post.structuredData && typeof post.structuredData === 'object' ? post.structuredData : null,
    html: String(post.html ?? '')
  };
}

function getPostsFromPayload(payload) {
  const posts = Array.isArray(payload) ? payload : payload?.posts;
  if (!Array.isArray(posts)) {
    throw new Error('Expected the posts JSON to be an array or an object with a posts array.');
  }

  return posts.map(normalizePost).filter((post) => post.slug && post.title && post.html);
}

async function loadPosts() {
  state.postsStatus = 'loading';
  state.postsError = '';

  try {
    const response = await fetch(POSTS_URL, { cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`Could not load ${POSTS_URL} (${response.status}).`);
    }

    state.posts = getPostsFromPayload(await response.json());
    state.postsStatus = 'ready';
  } catch (error) {
    state.posts = [];
    state.postsStatus = 'error';
    state.postsError = error instanceof Error ? error.message : 'Longball Notes could not be loaded.';
  }

  if (state.view === 'notes') {
    render();
  }
}

function getSeasonDataUrl(season) {
  return `/data/longball-index-${season}.json`;
}

async function fetchLeaderboardPayload(season) {
  const primaryUrl = getSeasonDataUrl(season);
  let response = await fetch(primaryUrl, { cache: 'no-store' });

  if (!response.ok && season === CURRENT_SEASON) {
    response = await fetch(DATA_URL, { cache: 'no-store' });
  }

  if (!response.ok) {
    throw new Error(`Could not load ${primaryUrl} (${response.status}).`);
  }

  return response.json();
}

async function loadLeaderboard(season = state.selectedSeason) {
  state.status = 'loading';
  state.error = '';
  state.selectedSeason = Number(season);
  if (state.view === 'home') {
    updateReadySections();
  }

  try {
    const payload = await fetchLeaderboardPayload(state.selectedSeason);
    const rows = getRowsFromPayload(payload);

    if (rows.length === 0) {
      throw new Error('The data file loaded, but it did not contain any valid player rows.');
    }

    state.dailyDongOverrides = await fetchDailyDongOverrides();
    state.rows = rows;
    state.generatedAt = String(payload?.generatedAt ?? '');
    state.dailyFeatures = applyDailyFeatureOverrides(normalizeDailyFeatures(payload?.dailyFeatures, payload?.dailyDong));
    state.dailyDong = state.dailyFeatures?.dailyDong ?? null;
    state.status = 'ready';
  } catch (error) {
    state.status = 'error';
    state.error = error instanceof Error ? error.message : 'The leaderboard could not be loaded.';
  }

  render();
}

async function fetchDailyDongOverrides() {
  try {
    const response = await fetch(DAILY_DONG_OVERRIDES_URL, { cache: 'no-store' });
    if (!response.ok) return {};
    const payload = await response.json();
    return payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : {};
  } catch {
    return {};
  }
}

function normalizeDailyFeatureEvent(event) {
  if (!event || typeof event !== 'object') return null;

  return {
    eventKey: String(event.eventKey ?? '').trim(),
    playId: String(event.playId ?? event.play_id ?? '').trim(),
    gameDate: String(event.gameDate ?? '').trim(),
    batter: String(event.batter ?? '').trim(),
    batterTeam: String(event.batterTeam ?? '').trim(),
    pitcher: String(event.pitcher ?? '').trim(),
    pitcherTeam: String(event.pitcherTeam ?? '').trim(),
    distance: event.distance == null ? null : Number(event.distance),
    exitVelocity: event.exitVelocity == null ? null : Number(event.exitVelocity),
    launchAngle: event.launchAngle == null ? null : Number(event.launchAngle),
    hrCat: String(event.hrCat ?? '').trim(),
    parksCleared: event.parksCleared == null ? null : Number(event.parksCleared),
    playUrl: event.playUrl ? String(event.playUrl) : '',
    overrideVideoUrl: event.overrideVideoUrl ? String(event.overrideVideoUrl) : '',
    overrideVideoLabel: event.overrideVideoLabel ? String(event.overrideVideoLabel) : '',
    score: event.score == null ? null : Number(event.score)
  };
}

function normalizeDailyFeatures(features, fallbackDailyDong) {
  const source = features && typeof features === 'object' ? features : {};

  return {
    gameDate: String(source.gameDate ?? fallbackDailyDong?.gameDate ?? '').trim(),
    dailyDong: normalizeDailyFeatureEvent(source.dailyDong ?? fallbackDailyDong),
    hotDogRobbery: normalizeDailyFeatureEvent(source.hotDogRobbery),
    cheapestDong: normalizeDailyFeatureEvent(source.cheapestDong)
  };
}

function dailyFeatureFallbackKey(event) {
  if (!event) return '';
  return [
    event.gameDate,
    event.batter,
    event.pitcher,
    event.distance == null ? '' : formatNumber(event.distance),
    event.exitVelocity == null ? '' : Number(event.exitVelocity).toFixed(1)
  ].join('|');
}

function findDailyFeatureOverride(event, featureKey) {
  if (!event) return null;

  return state.dailyDongOverrides[featureKey] ??
    state.dailyDongOverrides[event.playId] ??
    state.dailyDongOverrides[event.eventKey] ??
    state.dailyDongOverrides[dailyFeatureFallbackKey(event)] ??
    null;
}

function applyDailyFeatureOverride(event, featureKey) {
  const override = findDailyFeatureOverride(event, featureKey);

  if (!override || typeof override !== 'object') return event;

  return {
    ...event,
    overrideVideoUrl: override.videoUrl ? String(override.videoUrl) : '',
    overrideVideoLabel: override.videoLabel ? String(override.videoLabel) : ''
  };
}

function applyDailyFeatureOverrides(features) {
  if (!features) return null;

  return {
    ...features,
    dailyDong: applyDailyFeatureOverride(features.dailyDong, 'dailyDong'),
    hotDogRobbery: applyDailyFeatureOverride(features.hotDogRobbery, 'hotDogRobbery'),
    cheapestDong: applyDailyFeatureOverride(features.cheapestDong, 'cheapestDong')
  };
}

async function loadHotDogData() {
  try {
    const response = await fetch(HOT_DOG_URL, { cache: 'no-store' });

    if (!response.ok) {
      throw new Error(`Could not load ${HOT_DOG_URL} (${response.status}).`);
    }

    const payload = await response.json();
    state.hotDogPitchers = getHotDogRowsFromPayload(payload);
    state.hotDogGeneratedAt = String(payload?.generatedAt ?? '');
    state.hotDogStatus = 'ready';
  } catch (error) {
    state.hotDogStatus = 'error';
    state.hotDogError = error instanceof Error ? error.message : 'The Hot Dog Stand could not be loaded.';
  }

  updateHotDogSection();
}

function compareValues(a, b, column) {
  const aValue = column.key === 'rank' ? a.sourceRank : a[column.key];
  const bValue = column.key === 'rank' ? b.sourceRank : b[column.key];

  if (column.numeric) {
    return aValue - bValue;
  }

  return String(aValue).localeCompare(String(bValue));
}

function compareHotDogValues(a, b, column) {
  const aValue = column.key === 'rank' ? a.sourceRank : a[column.key];
  const bValue = column.key === 'rank' ? b.sourceRank : b[column.key];

  if (column.numeric) {
    return (aValue ?? 0) - (bValue ?? 0);
  }

  return String(aValue ?? '').localeCompare(String(bValue ?? ''));
}

function getVisibleRows() {
  const query = state.query.toLowerCase();

  return state.rows
    .filter((row) => row.hr >= state.minHr)
    .filter((row) => {
      return row.player.toLowerCase().includes(query) || row.team.toLowerCase().includes(query);
    })
    .sort((a, b) => {
      const column = columns.find((item) => item.key === state.sortKey);
      const direction = state.sortDirection === 'asc' ? 1 : -1;
      const primary = compareValues(a, b, column) * direction;

      if (primary !== 0) return primary;
      return b.hr - a.hr || a.player.localeCompare(b.player);
    })
    .map((row, index) => ({ ...row, rank: index + 1 }));
}

function getVisibleHotDogRows() {
  const query = state.hotDogQuery.toLowerCase();

  return state.hotDogPitchers
    .filter((pitcher) => pitcher.hrCapableBbeAllowed >= state.hotDogMinHrCapable)
    .filter((pitcher) => state.hotDogRole === 'all' || pitcher.pitcherRole === state.hotDogRole)
    .filter((pitcher) => {
      return pitcher.pitcher.toLowerCase().includes(query) || pitcher.team.toLowerCase().includes(query);
    })
    .sort((a, b) => {
      const column = hotDogColumns.find((item) => item.key === state.hotDogSortKey);
      const direction = state.hotDogSortDirection === 'asc' ? 1 : -1;
      const primary = compareHotDogValues(a, b, column) * direction;

      if (primary !== 0) return primary;
      return b.hrCapableBbeAllowed - a.hrCapableBbeAllowed || a.pitcher.localeCompare(b.pitcher);
    })
    .map((pitcher, index) => ({ ...pitcher, rank: index + 1 }));
}

function formatNumber(value, unit = '') {
  if (value == null || Number.isNaN(value)) {
    return 'N/A';
  }

  if (unit === 'percent') {
    return `${Math.round(value * 100)}%`;
  }

  const precision = unit === 'mph' || unit === 'lbi' ? 1 : 0;
  return `${value.toLocaleString(undefined, {
    maximumFractionDigits: precision,
    minimumFractionDigits: precision
  })}${unit && unit !== 'lbi' ? ` ${unit}` : ''}`;
}

function formatRelativeTime(value) {
  if (!value) return 'Updated recently';

  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return 'Updated recently';

  const seconds = Math.max(0, Math.floor((Date.now() - timestamp.getTime()) / 1000));
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) return `Updated ${days}d ago`;
  if (hours > 0) return `Updated ${hours}h ago`;
  if (minutes > 0) return `Updated ${minutes}m ago`;
  return 'Updated just now';
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function normalizeName(value) {
  return String(value ?? '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[’']/g, '')
    .toLowerCase()
    .trim();
}

function renderSortIcon(column, sortKey = state.sortKey, sortDirection = state.sortDirection) {
  if (sortKey !== column.key) return '<span class="sort-icon inactive">↕</span>';
  return `<span class="sort-icon active">${sortDirection === 'asc' ? '↑' : '↓'}</span>`;
}

function renderControls() {
  return `
    <section class="toolbar" aria-label="Leaderboard controls">
      <label class="field">
        <span>Season</span>
        <select id="season-select">
          ${LBI_SEASONS.map((season) => `
            <option value="${season}" ${state.selectedSeason === season ? 'selected' : ''}>${season}</option>
          `).join('')}
        </select>
      </label>
      <label class="field">
        <span>Search</span>
        <input id="search-input" type="search" placeholder="Player or team" value="${escapeHtml(state.query)}" />
      </label>
      <label class="field">
        <span>Minimum HR</span>
        <select id="min-hr-select">
          ${[0, 1, 3, 5, 10, 15, 20].map((value) => `
            <option value="${value}" ${state.minHr === value ? 'selected' : ''}>${value}+</option>
          `).join('')}
        </select>
      </label>
    </section>
  `;
}

function renderHotDogControls() {
  return `
    <section class="toolbar" aria-label="Hot Dog Stand controls">
      <label class="field">
        <span>Search</span>
        <input id="hot-dog-search-input" type="search" placeholder="Pitcher or team" value="${escapeHtml(state.hotDogQuery)}" />
      </label>
      <label class="field">
        <span>Minimum HR-Capable BBE</span>
        <select id="hot-dog-min-select">
          ${[0, 3, 5, 8, 10, 15, 20].map((value) => `
            <option value="${value}" ${state.hotDogMinHrCapable === value ? 'selected' : ''}>${value}+</option>
          `).join('')}
        </select>
      </label>
      <label class="field">
        <span>Pitcher Role</span>
        <select id="hot-dog-role-select">
          ${[
            ['all', 'All'],
            ['SP', 'SP'],
            ['RP', 'RP']
          ].map(([value, label]) => `
            <option value="${value}" ${state.hotDogRole === value ? 'selected' : ''}>${label}</option>
          `).join('')}
        </select>
      </label>
    </section>
  `;
}

function renderFeatureRow(row, value, meta = '') {
  return `
    <li class="feature-row">
      <span class="team">${escapeHtml(row.team)}</span>
      <span class="feature-player">${escapeHtml(row.player)}</span>
      <strong>${value}</strong>
      ${meta ? `<small>${meta}</small>` : ''}
    </li>
  `;
}

function hasActualCheapieData(row) {
  return Number.isFinite(row.actualDoubterHr) && row.hr >= 5;
}

function getActualCheapieRate(row) {
  if (!hasActualCheapieData(row) || row.hr <= 0) return 0;
  return Math.min(row.actualDoubterHr / row.hr, 1);
}

function renderJackedUpRow(row, rank) {
  return `
    <li class="card-row card-row--jacked">
      <span class="card-row__rank">${rank}</span>
      <div class="card-row__body">
        <div class="card-row__player">${escapeHtml(row.player)}</div>
        <div class="card-row__meta">${escapeHtml(row.team)} · LBI ${formatNumber(row.longballIndex, 'lbi')}</div>
      </div>
      <div class="card-row__value">${formatNumber(row.longestHr)}<span class="card-row__unit">ft</span></div>
    </li>
  `;
}

function renderIndexRow(row, rank) {
  return `
    <li class="card-row card-row--index">
      <span class="card-row__rank">${rank}</span>
      <div class="card-row__body">
        <div class="card-row__player">${escapeHtml(row.player)}</div>
        <div class="card-row__team-code">${escapeHtml(row.team)}</div>
      </div>
      <div class="card-row__lbi">${formatNumber(row.longballIndex, 'lbi')}</div>
    </li>
  `;
}

function renderCheapieRow(row, rank) {
  const hasActualData = hasActualCheapieData(row);
  const headline = hasActualData
    ? formatNumber(getActualCheapieRate(row), 'percent')
    : `${formatNumber(row.avgDistance)}<span class="card-row__unit">ft avg</span>`;
  const meta = hasActualData
    ? `${formatNumber(row.actualDoubterHr)} Cheapies / ${formatNumber(row.hr)} HR`
    : `${formatNumber(row.hr)} HR`;

  return `
    <li class="card-row card-row--cheapie">
      <span class="card-row__rank">${rank}</span>
      <div class="card-row__body">
        <div class="card-row__player">${escapeHtml(row.player)}</div>
        <div class="card-row__meta">${escapeHtml(row.team)} · ${meta}</div>
      </div>
      <div class="card-row__value card-row__value--muted">${headline}</div>
    </li>
  `;
}

function formatRate(value) {
  if (value == null || Number.isNaN(value)) return 'N/A';
  return value.toFixed(3).replace(/^0/, '');
}

function renderHotDogRow(pitcher, rank, options) {
  const meta = pitcher.team ? `${escapeHtml(pitcher.team)} · ${options.contextLine}` : options.contextLine;
  return `
    <li class="card-row card-row--${options.variant}">
      <span class="card-row__rank">${rank}</span>
      <div class="card-row__body">
        <div class="card-row__player">${escapeHtml(pitcher.pitcher)}</div>
        <div class="card-row__meta">${meta}</div>
      </div>
      <div class="card-row__value">${options.headlineValue}</div>
    </li>
  `;
}

function renderHotDogSection(pitchers) {
  if (state.hotDogStatus === 'loading') {
    return '';
  }

  if (state.hotDogStatus === 'error') {
    return `
      <section class="hot-dog-section" aria-label="The Hot Dog Stand">
        <div class="message error">
          <h2>Hot Dog Stand unavailable</h2>
          <p>${escapeHtml(state.hotDogError)}</p>
        </div>
      </section>
    `;
  }

  if (!pitchers.length) return '';

  const topDogs = [...pitchers]
    .filter((pitcher) => pitcher.hrsAllowed >= 5 && pitcher.hotDogIndex != null)
    .sort((a, b) => {
      return b.hotDogIndex - a.hotDogIndex || b.hrCapableBbeAllowed - a.hrCapableBbeAllowed || a.pitcher.localeCompare(b.pitcher);
    })
    .slice(0, 4);
  const footlongs = [...pitchers]
    .filter((pitcher) => pitcher.hrCapableBbeAllowed >= 1)
    .sort((a, b) => {
      return b.hrCapableBbeAllowed - a.hrCapableBbeAllowed || b.hotDogIndex - a.hotDogIndex || a.pitcher.localeCompare(b.pitcher);
    })
    .slice(0, 4);
  const extraMustard = [...pitchers]
    .filter((pitcher) => pitcher.noDoubtersAllowed >= 1)
    .sort((a, b) => {
      return b.noDoubtersAllowed - a.noDoubtersAllowed || b.hrCapableBbeAllowed - a.hrCapableBbeAllowed || a.pitcher.localeCompare(b.pitcher);
    })
    .slice(0, 4);
  const cooked = [...pitchers]
    .filter((pitcher) => pitcher.totalBbeAllowed >= 40 && pitcher.hrCapableBbeAllowed >= 3 && pitcher.cookedPer100Bbe != null)
    .sort((a, b) => {
      return b.cookedPer100Bbe - a.cookedPer100Bbe || b.hotDogIndex - a.hotDogIndex || a.pitcher.localeCompare(b.pitcher);
    })
    .slice(0, 4);

  return `
    <section class="hot-dog-section" aria-label="The Hot Dog Stand">
      <svg class="hot-dog-divider" viewBox="0 0 1200 8" preserveAspectRatio="none" aria-hidden="true">
        <line x1="0" y1="4" x2="1200" y2="4" stroke="currentColor" stroke-width="1.5" stroke-dasharray="4 4"/>
      </svg>
      <header class="hot-dog-header">
        <div class="hot-dog-header__main">
          <p class="hot-dog-header__eyebrow hot-dog-eyebrow">Pitcher Accountability</p>
          <h2 class="hot-dog-header__title">The Hot Dog Stand</h2>
          <p class="hot-dog-header__tagline">With extra mustard.</p>
          <p class="hot-dog-header__explainer">
            The <strong>Hot Dog Index</strong> measures loud, home-run-quality contact allowed
            by pitchers using Baseball Savant Home Run Tracker and Statcast event data.
          </p>
        </div>
        <a class="methodology-inline-link methodology-inline-link--top" href="${ROUTES.hotDog}">View full Hot Dog Index →</a>
      </header>

      <div class="hot-dog-grid">
        <article class="feature-card feature-card--topdog">
          <svg class="feature-card__arc" viewBox="0 0 200 60" aria-hidden="true">
            <path d="M 10 55 Q 100 -15 195 35" stroke="currentColor" stroke-width="2" fill="none" stroke-dasharray="3 3"/>
            <circle cx="195" cy="35" r="3" fill="currentColor"/>
          </svg>
          <p class="feature-card__eyebrow">WITH EXTRA MUSTARD</p>
          <h3 class="feature-card__title">TOP DOGS</h3>
          <p class="feature-card__subtitle">The highest Hot Dog Index scores.</p>
          <ol class="feature-card__list">
            ${topDogs.map((pitcher, index) => renderHotDogRow(pitcher, index + 1, {
              variant: 'topdog',
              headlineValue: formatNumber(pitcher.hotDogIndex, 'lbi'),
              contextLine: `${formatNumber(pitcher.hrCapableBbeAllowed)} HR-capable BBE`
            })).join('')}
          </ol>
        </article>

        <article class="feature-card feature-card--footlong">
          <div class="feature-card__topbar">
            <p class="feature-card__eyebrow">Long Line at the Stand</p>
            <span class="feature-card__live">5+ HR</span>
          </div>
          <h3 class="feature-card__title">FOOTLONGS</h3>
          <p class="feature-card__subtitle">Most HR-capable batted balls allowed.</p>
          <ol class="feature-card__list">
            ${footlongs.map((pitcher, index) => renderHotDogRow(pitcher, index + 1, {
              variant: 'footlong',
              headlineValue: formatNumber(pitcher.hrCapableBbeAllowed),
              contextLine: `${formatNumber(pitcher.hrsAllowed)} actual HR`
            })).join('')}
          </ol>
        </article>

        <article class="feature-card feature-card--mustard">
          <p class="feature-card__eyebrow">No-Doubter Damage</p>
          <h3 class="feature-card__title">EXTRA MUSTARD</h3>
          <p class="feature-card__subtitle">Balls that would leave every MLB park.</p>
          <ol class="feature-card__list">
            ${extraMustard.map((pitcher, index) => renderHotDogRow(pitcher, index + 1, {
              variant: 'mustard',
              headlineValue: formatNumber(pitcher.noDoubtersAllowed),
              contextLine: `${formatNumber(pitcher.hrCapableBbeAllowed)} HR-capable BBE`
            })).join('')}
          </ol>
        </article>

        <article class="feature-card feature-card--cooked">
          <div class="feature-card__topbar">
            <p class="feature-card__eyebrow">ON THE GRILL</p>
            <span class="feature-card__live">Damage / 100 BBE</span>
          </div>
          <h3 class="feature-card__title">COOKED</h3>
          <p class="feature-card__subtitle">Most Hot Dog damage allowed per 100 balls in play.</p>
          <ol class="feature-card__list">
            ${cooked.map((pitcher, index) => renderHotDogRow(pitcher, index + 1, {
              variant: 'cooked',
              headlineValue: formatNumber(pitcher.cookedPer100Bbe, 'lbi'),
              contextLine: `${formatNumber(pitcher.hrCapableBbeAllowed)} HR-capable BBE`
            })).join('')}
          </ol>
        </article>
      </div>
      <a class="methodology-inline-link" href="${getConceptUrl('hot-dog-stand-methodology')}">How the Hot Dog Index works →</a>
    </section>
  `;
}

function renderHotDogStoryCards(pitchers) {
  if (state.hotDogStatus !== 'ready' || !pitchers.length) return '';

  const topDogs = [...pitchers]
    .filter((pitcher) => pitcher.hrsAllowed >= 5 && pitcher.hotDogIndex != null)
    .sort((a, b) => {
      return b.hotDogIndex - a.hotDogIndex || b.hrCapableBbeAllowed - a.hrCapableBbeAllowed || a.pitcher.localeCompare(b.pitcher);
    })
    .slice(0, 5);
  const noDoubters = [...pitchers]
    .filter((pitcher) => pitcher.noDoubtersAllowed > 0)
    .sort((a, b) => {
      return b.noDoubtersAllowed - a.noDoubtersAllowed || b.hotDogIndex - a.hotDogIndex || a.pitcher.localeCompare(b.pitcher);
    })
    .slice(0, 5);
  const cooked = [...pitchers]
    .filter((pitcher) => pitcher.totalBbeAllowed >= 40 && pitcher.hrCapableBbeAllowed >= 3 && pitcher.cookedPer100Bbe != null)
    .sort((a, b) => {
      return b.cookedPer100Bbe - a.cookedPer100Bbe || b.hotDogIndex - a.hotDogIndex || a.pitcher.localeCompare(b.pitcher);
    })
    .slice(0, 5);

  return `
    <section class="hot-dog-page-cards hot-dog-grid" aria-label="Hot Dog Stand story cards">
      <article class="feature-card feature-card--topdog">
        <p class="feature-card__eyebrow">WITH EXTRA MUSTARD</p>
        <h3 class="feature-card__title">HOT DOG INDEX</h3>
        <p class="feature-card__subtitle">Total longball damage allowed.</p>
        <ol class="feature-card__list">
          ${topDogs.map((pitcher, index) => renderHotDogRow(pitcher, index + 1, {
            variant: 'topdog',
            headlineValue: formatNumber(pitcher.hotDogIndex, 'lbi'),
            contextLine: `${formatNumber(pitcher.hrCapableBbeAllowed)} HR-capable BBE`
          })).join('')}
        </ol>
      </article>

      <article class="feature-card feature-card--footlong">
        <div class="feature-card__topbar">
          <p class="feature-card__eyebrow">No-Doubter Damage</p>
        </div>
        <h3 class="feature-card__title">FOOTLONGS</h3>
        <p class="feature-card__subtitle">Gone everywhere.</p>
        <ol class="feature-card__list">
          ${noDoubters.map((pitcher, index) => renderHotDogRow(pitcher, index + 1, {
            variant: 'footlong',
            headlineValue: formatNumber(pitcher.noDoubtersAllowed),
            contextLine: `${formatNumber(pitcher.hrCapableBbeAllowed)} HR-capable BBE`
          })).join('')}
        </ol>
      </article>

      <article class="feature-card feature-card--wall-scraper">
        <div class="feature-card__topbar">
          <p class="feature-card__eyebrow">ON THE GRILL</p>
          <span class="feature-card__live">Damage / 100 BBE</span>
        </div>
        <h3 class="feature-card__title">COOKED</h3>
        <p class="feature-card__subtitle">Most Hot Dog damage allowed per 100 balls in play.</p>
        <ol class="feature-card__list">
          ${cooked.map((pitcher, index) => renderHotDogRow(pitcher, index + 1, {
            variant: 'wall-scraper',
            headlineValue: formatNumber(pitcher.cookedPer100Bbe, 'lbi'),
            contextLine: `${formatNumber(pitcher.hrCapableBbeAllowed)} HR-capable BBE`
          })).join('')}
        </ol>
      </article>
    </section>
  `;
}

function renderFeatureCards(rows) {
  const updatedLabel = formatRelativeTime(state.generatedAt);
  const updatedTitle = state.generatedAt;
  const jackedUp = [...rows]
    .filter((row) => row.longestHr > 0)
    .sort((a, b) => b.longestHr - a.longestHr)
    .slice(0, 6);
  const lbiLeaders = [...rows].sort((a, b) => b.longballIndex - a.longballIndex).slice(0, 6);
  const actualCheapieRows = rows.filter(hasActualCheapieData);
  const hasActualCheapieClassifications = actualCheapieRows.length > 0;
  const cheapies = (actualCheapieRows.length ? actualCheapieRows : rows.filter((row) => (
    row.hr >= 5 &&
    Number.isFinite(row.avgDistance) &&
    row.avgDistance > 0
  )))
    .sort((a, b) => {
      if (actualCheapieRows.length) {
        const rateDiff = getActualCheapieRate(b) - getActualCheapieRate(a);
        if (rateDiff !== 0) return rateDiff;
        return b.actualDoubterHr - a.actualDoubterHr;
      }

      const distanceDiff = a.avgDistance - b.avgDistance;
      if (distanceDiff !== 0) return distanceDiff;
      return a.longestHr - b.longestHr;
    })
    .slice(0, 6);

  return `
    <section class="feature-grid" aria-label="The Long Ball feature modules">
      <article class="feature-card feature-card--index">
        <div class="feature-card__topbar">
          <p class="feature-card__eyebrow">THE INDEX</p>
          <span class="feature-card__live" ${updatedTitle ? `title="${escapeHtml(updatedTitle)}"` : ''}>${escapeHtml(updatedLabel)}</span>
        </div>
        <h2 class="feature-card__title">LBI LEADERS</h2>
        <p class="feature-card__subtitle">Scaled like wRC+.</p>
        <ol class="feature-card__list">
          ${lbiLeaders.map((row, index) => renderIndexRow(row, index + 1)).join('')}
        </ol>
      </article>

      <article class="feature-card feature-card--jacked">
        <svg class="feature-card__arc" viewBox="0 0 200 60" aria-hidden="true">
          <path d="M 10 55 Q 100 -15 195 35" stroke="currentColor" stroke-width="2" fill="none" stroke-dasharray="3 3"/>
          <circle cx="195" cy="35" r="3" fill="currentColor"/>
        </svg>
        <p class="feature-card__eyebrow">GOODBYE, BASEBALL</p>
        <h2 class="feature-card__title">JACKED UP</h2>
        <p class="feature-card__subtitle">The farthest this season.</p>
        <ol class="feature-card__list">
          ${jackedUp.map((row, index) => renderJackedUpRow(row, index + 1)).join('')}
        </ol>
      </article>

      <article class="feature-card feature-card--cheapie">
        <p class="feature-card__eyebrow feature-card__eyebrow--warn">⚠ PARK EFFECTS ABUSED</p>
        <h2 class="feature-card__title">CHEAPIES</h2>
        <p class="feature-card__subtitle">${hasActualCheapieClassifications ? 'Actual HR that would clear only 1–7 parks.' : 'Shortest avg HR distance proxy.'}</p>
        <ol class="feature-card__list">
          ${cheapies.map((row, index) => renderCheapieRow(row, index + 1)).join('')}
        </ol>
      </article>
    </section>
  `;
}

function dailyFeatureDetailLine(event) {
  const pieces = [
    event.distance == null ? null : formatNumber(event.distance, 'ft'),
    event.exitVelocity == null ? null : formatNumber(event.exitVelocity, 'mph'),
    event.eventOutcome && event.eventOutcome !== 'Home Run' ? event.eventOutcome : null,
    event.hrCat || null,
    event.parksCleared == null ? null : `${formatNumber(event.parksCleared)}/30 parks`
  ].filter(Boolean);

  return pieces.join(' · ');
}

function isPublicVideoUrl(value) {
  return Boolean(value) && !value.includes('research.mlb.com') && !value.includes('/login');
}

function dailyFeatureTitleLine(featureKey, event, context) {
  if (!event) return null;

  if (featureKey === 'dailyDong') {
    return context === 'pitcher'
      ? `${event.pitcher || 'Unknown pitcher'} served it up to ${event.batter || 'Unknown hitter'}`
      : `${event.batter || 'Unknown hitter'} took ${event.pitcher || 'Unknown pitcher'} deep`;
  }

  if (featureKey === 'hotDogRobbery') {
    return `${event.batter || 'Unknown hitter'} nearly got ${event.pitcher || 'Unknown pitcher'}`;
  }

  return `${event.batter || 'Unknown hitter'} snuck one out against ${event.pitcher || 'Unknown pitcher'}`;
}

function renderDailyFeatureCard(featureKey, config, context = 'hitter') {
  const event = state.dailyFeatures?.[featureKey] ?? null;
  const isPitcherContext = context === 'pitcher';
  const overrideUrl = event?.overrideVideoUrl ?? '';
  const playUrl = overrideUrl || event?.playUrl || '';
  const hasPublicPlayUrl = isPublicVideoUrl(playUrl);
  const playLabel = event?.overrideVideoLabel || 'Watch / View play';
  const titleLine = dailyFeatureTitleLine(featureKey, event, context) ?? `No ${config.title} available yet.`;
  const teamLine = event
    ? (isPitcherContext
      ? `${event.pitcherTeam || '—'} pitching · ${event.batterTeam || '—'} batting`
      : `${event.batterTeam || '—'} batting · ${event.pitcherTeam || '—'} pitching`)
    : '';

  return `
    <article class="daily-feature daily-feature--${featureKey}">
      <div class="daily-feature__label">
        <h2>${config.title}</h2>
      </div>
      <div class="daily-feature__body">
        <strong>${escapeHtml(titleLine)}</strong>
        ${event ? `<span>${escapeHtml(teamLine)}</span>` : ''}
        ${event ? `<span>${escapeHtml(dailyFeatureDetailLine(event))}</span>` : ''}
      </div>
      ${hasPublicPlayUrl ? `<a class="methodology-inline-link" href="${escapeHtml(playUrl)}" target="_blank" rel="noreferrer">${escapeHtml(playLabel)} →</a>` : ''}
    </article>
  `;
}

function renderDailyFeatureStrip(context = 'hitter') {
  const configs = [
    ['dailyDong', { title: 'DAILY DONG' }],
    ['hotDogRobbery', { title: 'HOT DOG ROBBERY' }],
    ['cheapestDong', { title: 'CHEAPEST DONG' }]
  ];

  return `
    <section class="daily-feature-section daily-feature-section--${context}" aria-label="Daily longball features">
      <header class="daily-feature-section__header">
        <p class="eyebrow">TALE OF THE TAPE</p>
        <p>Today’s longball ledger.</p>
      </header>
      <div class="daily-feature-strip">
        ${configs.map(([featureKey, config]) => renderDailyFeatureCard(featureKey, config, context)).join('')}
      </div>
    </section>
  `;
}

function renderTable(rows) {
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            ${columns.map((column) => `
              <th scope="col">
                <button class="sort-button" data-sort-key="${column.key}">
                  <span class="label-full">${column.label}</span>
                  <span class="label-short">${column.shortLabel ?? column.label}</span>
                  ${renderSortIcon(column)}
                </button>
              </th>
            `).join('')}
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr class="clickable-row" data-player-id="${row.batter}" tabindex="0" role="button" aria-label="Open ${escapeHtml(row.player)} detail">
              <td class="rank">${row.rank}</td>
              <td class="player">${escapeHtml(row.player)}</td>
              <td><span class="team">${escapeHtml(row.team)}</span></td>
              <td class="lbi">${formatNumber(row.longballIndex, 'lbi')}</td>
              <td>${formatNumber(row.bbe)}</td>
              <td>${formatNumber(row.hr)}</td>
              <td>${formatNumber(row.xhrPerBbe, 'percent')}</td>
              <td>${formatNumber(row.barrelRate, 'percent')}</td>
              <td>${formatNumber(row.hardHitRate, 'percent')}</td>
              <td>${formatNumber(row.avgDistanceOnBarrels, 'ft')}</td>
              <td>${formatNumber(row.pullAirRate, 'percent')}</td>
              <td>${formatNumber(row.sweetSpotRate, 'percent')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderHotDogTable(rows) {
  return `
    <div class="table-wrap">
      <table class="hot-dog-table">
        <thead>
          <tr>
            ${hotDogColumns.map((column) => `
              <th scope="col">
                <button class="sort-button" data-hot-dog-sort-key="${column.key}">
                  <span class="label-full">${column.label}</span>
                  <span class="label-short">${column.shortLabel ?? column.label}</span>
                  ${renderSortIcon(column, state.hotDogSortKey, state.hotDogSortDirection)}
                </button>
              </th>
            `).join('')}
          </tr>
        </thead>
        <tbody>
          ${rows.map((pitcher) => `
            <tr class="clickable-row" data-pitcher-id="${pitcher.pitcherId}" tabindex="0" role="button" aria-label="Open ${escapeHtml(pitcher.pitcher)} detail">
              <td class="rank">${pitcher.rank}</td>
              <td class="player">${escapeHtml(pitcher.pitcher)}</td>
              <td><span class="team">${escapeHtml(pitcher.team || '—')}</span></td>
              <td>${escapeHtml(pitcher.pitcherRole || '—')}</td>
              <td class="lbi">${formatNumber(pitcher.hotDogIndex, 'lbi')}</td>
              <td>${formatNumber(pitcher.cookedPer100Bbe, 'lbi')}</td>
              <td>${formatNumber(pitcher.totalBbeAllowed)}</td>
              <td>${formatNumber(pitcher.hrCapableBbeAllowed)}</td>
              <td>${formatNumber(pitcher.noDoubtersAllowed)}</td>
              <td>${formatNumber(pitcher.mostlyGoneAllowed)}</td>
              <td>${formatNumber(pitcher.doubtersAllowed)}</td>
              <td>${formatNumber(pitcher.avgExitVelocityAllowed, 'mph')}</td>
              <td>${formatNumber(pitcher.avgDistanceAllowed, 'ft')}</td>
              <td>${formatNumber(pitcher.maxDistanceAllowed, 'ft')}</td>
              <td>${formatNumber(pitcher.maxExitVelocityAllowed, 'mph')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function launchArcPath(angle) {
  const clamped = Math.max(8, Math.min(42, Number(angle)));
  const endY = Math.max(24, 86 - (clamped - 8) * 1.15);
  const controlY = Math.max(8, 86 - clamped * 2.1);
  return `M 20 92 C 58 ${controlY}, 112 ${controlY}, 178 ${endY}`;
}

function damageArcPath(angle, distance) {
  const clampedAngle = Math.max(8, Math.min(42, Number(angle) || 28));
  const clampedDistance = Math.max(350, Math.min(480, Number(distance) || 400));
  const distanceBoost = (clampedDistance - 350) / 130;
  const endX = 154 + distanceBoost * 30;
  const endY = Math.max(22, 88 - (clampedAngle - 8) * 1.1 - distanceBoost * 8);
  const controlY = Math.max(8, 88 - clampedAngle * 1.9 - distanceBoost * 14);
  return `M 20 92 C 58 ${controlY}, 110 ${controlY}, ${endX} ${endY}`;
}

function renderLaunchAngleSketch(player) {
  const angle = player.avgLaunchAngleOnBarrels;

  if (angle == null || Number.isNaN(angle)) {
    return `
      <section class="launch-sketch launch-sketch--empty">
        <div>
          <h3>Launch Angle Sketch</h3>
          <p>Avg barrel launch angle</p>
        </div>
        <div class="launch-sketch__empty">Not enough barreled contact yet.</div>
        <small>Sketch only — not a ball-flight simulation.</small>
      </section>
    `;
  }

  return `
    <section class="launch-sketch">
      <div class="launch-sketch__header">
        <div>
          <h3>Launch Angle Sketch</h3>
          <p>Avg barrel launch angle</p>
        </div>
        <strong>${formatNumber(angle)}°</strong>
      </div>
      <svg class="launch-sketch__svg" viewBox="0 0 200 110" role="img" aria-label="Launch angle sketch for ${escapeHtml(player.player)}">
        <line x1="16" y1="92" x2="186" y2="92" />
        <path d="${launchArcPath(angle)}" />
        <circle cx="20" cy="92" r="4" />
      </svg>
      <small>Sketch only — not a ball-flight simulation.</small>
    </section>
  `;
}

function statAvailable(value) {
  return value != null && !Number.isNaN(value);
}

function renderDetailBadges(badges) {
  if (!badges.length) return '';
  return `
    <div class="scouting-card__badges" aria-label="Player context">
      ${badges.map((badge) => `<span class="scouting-badge scouting-badge--${badge.tone ?? 'neutral'}">${escapeHtml(badge.label)}</span>`).join('')}
    </div>
  `;
}

function renderDetailStatGrid(items, className = '') {
  return `
    <div class="detail-stat-grid ${className}">
      ${items.map((item) => `
        <div class="detail-stat">
          <span>${escapeHtml(item.label)}</span>
          <strong>${item.value}</strong>
          ${item.helper ? `<small>${escapeHtml(item.helper)}</small>` : ''}
        </div>
      `).join('')}
    </div>
  `;
}

function getHitterContext(player) {
  const xHrDiff = statAvailable(player.xhrDiff) ? player.xhrDiff : 0;
  const hasActualCheapies = Number.isFinite(player.actualDoubterHr);
  const cheapieCount = hasActualCheapies ? player.actualDoubterHr : 0;
  const cheapieRate = hasActualCheapies && player.hr > 0 ? Math.min(cheapieCount / player.hr, 1) : null;
  const hrPace = player.pa > 0 ? (player.hr / player.pa) * 600 : 0;
  const isPowerGap = xHrDiff >= 1.5 && player.longballIndex >= 110 && player.hr >= 5;
  const isPowerMirage = player.hr >= 5 && ((-xHrDiff) >= 1.5 || (cheapieRate != null && cheapieRate >= 0.25 && player.longballIndex < 145));
  const isSurprisePop = player.longballIndex >= 110 && player.hr >= 5 && hrPace < 40 && player.sourceRank > 20;
  const taleEvents = [
    ['Daily Dong', state.dailyFeatures?.dailyDong],
    ['Tale of the Tape', state.dailyFeatures?.hotDogRobbery],
    ['Tale of the Tape', state.dailyFeatures?.cheapestDong]
  ];
  const hasTale = taleEvents.find(([, event]) => {
    return event && (Number(event.batterId) === player.batter || normalizeName(event.batter) === normalizeName(player.player));
  });
  const badges = [];
  if (isPowerGap) badges.push({ label: 'Power Gap', tone: 'red' });
  if (isSurprisePop) badges.push({ label: 'Surprise Pop', tone: 'mustard' });
  if (isPowerMirage) badges.push({ label: 'Power Mirage', tone: 'muted' });
  if (hasTale) badges.push({ label: hasTale[0], tone: 'ink' });

  let why = 'Longball contact quality stands out in the current profile.';
  if (player.longballIndex >= 160 && player.hrWindowThunderRate >= 0.055) {
    why = 'Elite LBI with repeated HR-window thunder.';
  } else if (isPowerGap) {
    why = 'Expected HR is running ahead of actual HR, and LBI supports the gap.';
  } else if (isSurprisePop) {
    why = 'Non-obvious power signal with real longball ingredients.';
  } else if (isPowerMirage) {
    why = 'HR total has more short-porch context than the LBI fully supports.';
  } else if (player.hrWindowThunderRate >= 0.05) {
    why = 'HR-window thunder is carrying a real longball shape.';
  } else if (player.barrelRate >= 0.14 && player.longballIndex >= 125) {
    why = 'Barrel quality and LBI are both supporting the profile.';
  }

  return {
    badges,
    why,
    cheapieCount,
    cheapieRate,
    hrPace
  };
}

function renderPlayerDetailModal() {
  const player = state.rows.find((row) => row.batter === state.selectedPlayerId);
  if (!player) return '';
  const hitterContext = getHitterContext(player);
  const xHrDiffValue = statAvailable(player.xhrDiff) && player.xhrDiff > 0
    ? `+${formatNumber(player.xhrDiff, 'lbi')}`
    : formatNumber(player.xhrDiff, 'lbi');
  const pullAirJuiceValue = player.pullAirJuicePer100Pa == null
    ? 'N/A'
    : formatNumber(player.pullAirJuicePer100Pa, 'lbi');
  const meta = [player.team, player.position].filter(Boolean).join(' · ') || '—';

  return `
    <div class="modal-backdrop" data-detail-backdrop>
      <section class="player-modal scouting-card" role="dialog" aria-modal="true" aria-labelledby="player-detail-title">
        <button class="modal-close" type="button" data-detail-close aria-label="Close player detail">×</button>
        <header class="scouting-card__header">
          <p class="eyebrow">Long Ball Scouting Card</p>
          <h2 id="player-detail-title">${escapeHtml(player.player)}</h2>
          <p class="player-modal__team">${escapeHtml(meta)}</p>
          ${renderDetailBadges(hitterContext.badges)}
        </header>

        <section class="scouting-hero scouting-hero--hitter" aria-label="Hero stat">
          <div>
            <span>LBI</span>
            <strong>${formatNumber(player.longballIndex, 'lbi')}</strong>
          </div>
          <p>Rank ${formatNumber(player.sourceRank)} · Longball quality per batted ball.</p>
        </section>

        <section class="scouting-callout" aria-label="Why he's here">
          <h3>Why he’s here</h3>
          <p>${escapeHtml(hitterContext.why)}</p>
        </section>

        <section class="scouting-section" aria-label="Key hitter stats">
          <h3>Key Stats</h3>
          ${renderDetailStatGrid([
            { label: 'LBI', value: formatNumber(player.longballIndex, 'lbi') },
            { label: 'HR', value: formatNumber(player.hr) },
            { label: 'xHR Diff', value: xHrDiffValue },
            { label: 'HR-Window Thunder', value: formatNumber(player.hrWindowThunderRate, 'percent') },
            { label: 'Barrel%', value: formatNumber(player.barrelRate, 'percent') },
            { label: 'Hard Hit%', value: formatNumber(player.hardHitRate, 'percent') }
          ])}
        </section>

        <section class="scouting-section" aria-label="Contact shape">
          <h3>Contact Shape</h3>
          ${renderDetailStatGrid([
            { label: 'Avg Barrel LA', value: statAvailable(player.avgLaunchAngleOnBarrels) ? `${formatNumber(player.avgLaunchAngleOnBarrels)}°` : 'N/A' },
            { label: 'Avg Barrel Dist', value: formatNumber(player.avgDistanceOnBarrels, 'ft') },
            { label: 'Pull-Air Juice', value: pullAirJuiceValue, helper: 'Weighted pulled airborne damage per 100 PA.' }
          ], 'detail-stat-grid--three')}
          ${renderLaunchAngleSketch(player)}
        </section>
      </section>
    </div>
  `;
}

function getWorstServedName(event) {
  const description = String(event?.description ?? '');
  const upheldMatch = description.match(/upheld:\s*([^:.,]+?)\s+homers/i);
  const homerMatch = description.match(/([A-ZÀ-ÖØ-öø-ÿ' .-]+?)\s+homers/i);
  const name = upheldMatch?.[1] ?? homerMatch?.[1] ?? '';
  return name.trim();
}

function renderWorstServed(pitcher) {
  const event = pitcher.worstServedEvent;
  if (!event) return '';

  const batter = getWorstServedName(event) || (event.batterId ? `MLBAM ${event.batterId}` : 'Unknown hitter');
  const distance = formatNumber(event.distance, 'ft');
  const exitVelocity = formatNumber(event.exitVelocity, 'mph');

  return `
    <p class="worst-served">
      <strong>Worst served:</strong>
      ${escapeHtml(batter)} — ${distance}, ${exitVelocity}
    </p>
  `;
}

function renderServedUpSketch(pitcher) {
  const eventAngle = pitcher.worstServedEvent?.launchAngle == null ? null : Number(pitcher.worstServedEvent.launchAngle);
  const angle = pitcher.avgLaunchAngleAllowed ?? eventAngle;
  const distance = pitcher.maxDistanceAllowed ?? pitcher.avgDistanceAllowed;
  const hasAngle = angle != null && Number.isFinite(angle);
  const angleLabel = hasAngle ? `${formatNumber(angle)}°` : 'Generic arc';
  const detail = hasAngle ? 'Launch angle from served-up contact' : 'Sketch based on HR-capable contact allowed.';

  return `
    <section class="launch-sketch launch-sketch--served">
      <div class="launch-sketch__header">
        <div>
          <h3>Served Up Sketch</h3>
          <p>HR-capable contact allowed</p>
        </div>
        <strong>${angleLabel}</strong>
      </div>
      <svg class="launch-sketch__svg" viewBox="0 0 200 110" role="img" aria-label="Served up contact sketch for ${escapeHtml(pitcher.pitcher)}">
        <line x1="16" y1="92" x2="186" y2="92" />
        <path d="${damageArcPath(angle, distance)}" />
        <circle cx="20" cy="92" r="4" />
      </svg>
      <p class="launch-sketch__caption">${detail}</p>
      <small>Sketch only — not a pitch-tracking simulation.</small>
    </section>
  `;
}

function getPitcherContext(pitcher) {
  const badges = [];
  const bbeAllowed = pitcher.totalBbeAllowed || pitcher.bbeAllowed;
  const limitedSample = bbeAllowed > 0 && bbeAllowed < 175;
  if (pitcher.hotDogIndex >= 130 || pitcher.cookedPer100Bbe >= 130) badges.push({ label: 'Getting Cooked', tone: 'mustard' });
  if (statAvailable(pitcher.stackWatchScore)) badges.push({ label: 'Stack Watch', tone: 'red' });
  if (limitedSample) badges.push({ label: 'Limited Sample', tone: 'muted' });

  let why = 'Pitcher-side longball damage is showing up in the allowed-contact profile.';
  if (limitedSample && pitcher.cookedPer100Bbe >= 130) {
    why = 'Cooked rate spike, but sample is limited.';
  } else if (pitcher.hrWindowThunderRateAllowed >= 0.045) {
    why = 'HR-window thunder allowed is carrying the profile.';
  } else if (pitcher.hotDogIndex >= 135) {
    why = 'HDI backs the longball damage.';
  } else if (pitcher.noDoubterRateAllowed >= 0.01 && pitcher.hrCapableBbeRateAllowed >= 0.14) {
    why = 'Premium contact allowed: no-doubter damage and HR-capable contact are both flashing.';
  } else if (pitcher.cookedPer100Bbe >= 130) {
    why = 'Cooked rate spike is the main warning light.';
  } else if (pitcher.hrCapableBbeRateAllowed >= 0.14) {
    why = 'HR-capable contact allowed is the clearest signal.';
  }

  return { badges, why, limitedSample };
}

function renderPitcherDetailModal() {
  const pitcher = state.hotDogPitchers.find((row) => row.pitcherId === state.selectedPitcherId);
  if (!pitcher) return '';
  const context = getPitcherContext(pitcher);
  const bbeAllowed = pitcher.totalBbeAllowed || pitcher.bbeAllowed;
  const roleMeta = pitcher.pitcherRole ? ` · ${pitcher.pitcherRole}` : '';
  const stackContext = statAvailable(pitcher.stackWatchScore) || pitcher.stackWatchSampleTag || statAvailable(pitcher.opponentLineupAvgLbi) || pitcher.parkHrTag;

  return `
    <div class="modal-backdrop" data-pitcher-detail-backdrop>
      <section class="player-modal player-modal--pitcher scouting-card" role="dialog" aria-modal="true" aria-labelledby="pitcher-detail-title">
        <button class="modal-close" type="button" data-pitcher-detail-close aria-label="Close pitcher detail">×</button>
        <header class="scouting-card__header">
          <p class="eyebrow hot-dog-eyebrow">Hot Dog Scouting Card</p>
          <h2 id="pitcher-detail-title">${escapeHtml(pitcher.pitcher)}</h2>
          <p class="player-modal__team">${escapeHtml(pitcher.team || '—')}${escapeHtml(roleMeta)}</p>
          ${renderDetailBadges(context.badges)}
        </header>

        <section class="scouting-hero scouting-hero--pitcher" aria-label="Hero stat">
          <div>
            <span>HDI</span>
            <strong>${formatNumber(pitcher.hotDogIndex, 'lbi')}</strong>
          </div>
          <p>Rank ${formatNumber(pitcher.sourceRank)} · Pitcher-side longball damage allowed.</p>
        </section>

        <section class="scouting-callout scouting-callout--pitcher" aria-label="Why he's here">
          <h3>Why he’s here</h3>
          <p>${escapeHtml(context.why)}</p>
        </section>

        <section class="scouting-section" aria-label="Key pitcher stats">
          <h3>Key Stats</h3>
          ${renderDetailStatGrid([
            { label: 'HDI', value: formatNumber(pitcher.hotDogIndex, 'lbi') },
            { label: 'Cooked / 100 BBE', value: formatNumber(pitcher.cookedPer100Bbe, 'lbi') },
            { label: 'HR-Window Thunder Allowed', value: formatNumber(pitcher.hrWindowThunderRateAllowed, 'percent') },
            { label: 'Adj. xHR/BBE Allowed', value: formatNumber(pitcher.adjustedXhrPerBbeAllowed, 'percent') },
            { label: 'HR-Capable Rate', value: formatNumber(pitcher.hrCapableBbeRateAllowed, 'percent') },
            { label: 'No-Doubter Rate', value: formatNumber(pitcher.noDoubterRateAllowed, 'percent') }
          ])}
        </section>

        <section class="scouting-section" aria-label="Damage shape">
          <h3>Damage Shape</h3>
          ${renderDetailStatGrid([
            { label: 'Avg EV / HR', value: formatNumber(pitcher.avgExitVelocityAllowed, 'mph') },
            { label: 'Max EV Allowed', value: formatNumber(pitcher.maxExitVelocityAllowed, 'mph') },
            { label: 'BBE Allowed', value: formatNumber(bbeAllowed) },
            { label: 'HR Allowed', value: formatNumber(pitcher.hrsAllowed) }
          ])}
          ${renderWorstServed(pitcher)}
          ${renderServedUpSketch(pitcher)}
        </section>

        ${stackContext ? `
          <section class="scouting-section" aria-label="Stack Watch context">
            <h3>Stack Watch Context</h3>
            ${renderDetailStatGrid([
              { label: 'Stack Watch', value: formatNumber(pitcher.stackWatchScore, 'lbi') },
              { label: 'Sample', value: pitcher.stackWatchSampleTag ? escapeHtml(pitcher.stackWatchSampleTag) : 'N/A' },
              { label: 'Opp. Lineup LBI', value: formatNumber(pitcher.opponentLineupAvgLbi, 'lbi') },
              { label: 'Park HR Tag', value: pitcher.parkHrTag ? escapeHtml(pitcher.parkHrTag) : 'N/A' }
            ])}
          </section>
        ` : ''}
      </section>
    </div>
  `;
}

function renderFutureFeatures() {
  return `
    <section class="future">
      <h2>On deck</h2>
      <div class="future-grid">
        <span>Adjusted vs Standard Home Run Tracker toggle</span>
        <span>Daily Dong archive and video links</span>
        <span>CSS launch-angle visualizer</span>
      </div>
    </section>
  `;
}

function renderHotDogCrossLink() {
  return `
    <section class="hot-dog-crosslink" aria-label="Hot Dog Stand cross-link">
      <div>
        <p class="eyebrow">Pitcher Accountability</p>
        <h2>Looking for pitcher accountability?</h2>
        <p>The Hot Dog Stand tracks who's serving up baseball's loudest contact.</p>
      </div>
      <a class="methodology-inline-link" href="${ROUTES.hotDog}">View The Hot Dog Stand →</a>
    </section>
  `;
}

function renderScoutingReportPromo() {
  return `
    <section class="report-crosslink" aria-label="Longball Scouting Report">
      <div>
        <p class="eyebrow">Weekly Report</p>
        <h2>The Longball Scouting Report</h2>
        <p>Weekly risers, fallers, Power Gap, Power Mirage, and pitchers getting cooked.</p>
      </div>
      <a class="methodology-inline-link" href="${ROUTES.reports}">Read the latest report →</a>
    </section>
  `;
}

function renderHotDogMiniCallout() {
  return `
    <aside class="hot-dog-mini-callout" aria-label="Hot Dog Stand callout">
      <span>Looking for pitcher accountability?</span>
      <a href="${ROUTES.hotDog}">View The Hot Dog Stand →</a>
    </aside>
  `;
}

function renderAboutPage() {
  return `
    ${renderSiteNav('about')}

    <article class="about-page">
      <section class="about-section about-section--intro">
        <h2>About The Long Ball</h2>
        <p>The Longball Index (LBI) measures the quality of a hitter's contact, specifically tuned to home run production.</p>
      </section>

      <section class="about-section" id="longball-index">
        <h2>What Is the Longball Index?</h2>
        <p>LBI is a per-contact measure. It evaluates the quality of a hitter's batted balls and does not factor in how often they make contact. A hitter who barrels 20% of their batted balls but strikes out frequently can score higher than a hitter who rarely whiffs but rarely punishes the baseball. This is a deliberate choice: LBI answers "what kind of contact does this hitter produce?" not "how many home runs will this hitter hit?"</p>
        <p>Hitting metrics live in one of three layers. Layer one is results: HR, ISO, SLG, what actually happened. Layer two is expected results: xHR, xSLG, xwOBA, what should have happened given the inputs. Layer three is underlying quality: Barrel%, Exit Velocity, Hard Hit%, the physics of the swing itself, separated from outcomes and from prediction. ISO lives in layer one. xISO lives in layer two. LBI is the first composite metric purpose-built for home run quality in layer three.</p>
      </section>

      <section class="about-section">
        <h2>Why Not Just Use ISO?</h2>
        <p>Maybe I'm just old school, or slow to change, but my first go-to power metric has always been ISO. Slugging minus batting average, it's simple, durable, and quickly tells you how much extra-base damage a player is producing. Crack .200 and I'm interested. A .150 guy? Ok, he can hold his own. A .250 guy, legit power. The .300 guys are unicorns. But ISO has severe limitations, baking in everything you can't separate from a hitter's swing: stadium, defense, sequencing, luck. A 340-foot fly ball can be an easy home run in Boston and a lazy flyout in Detroit.</p>
      </section>

      <section class="about-section" id="longball-index-methodology">
        <h2>LBI v1.3 Methodology</h2>
        <p>LBI v1.3 is anchored by Adjusted xHR/BBE and sharpened by Barrel%, HR-Window Thunder Rate, and Hard Hit%.</p>
        <ul class="about-list">
          <li><strong>Adjusted xHR/BBE</strong>: stadium-neutral home-run quality anchor</li>
          <li><strong>Barrel%</strong>: home-run-quality contact rate</li>
          <li><strong>HR-Window Thunder Rate</strong>: 105+ mph batted balls launched between 25° and 40°, per BBE</li>
          <li><strong>Hard Hit%</strong>: small raw-impact stabilizer</li>
        </ul>

        <div class="method-grid" aria-label="LBI v1.3 weights">
          <section>
            <h3>LBI v1.3 formula</h3>
            <ul>
              <li>Adjusted xHR/BBE: 50%</li>
              <li>Barrel%: 20%</li>
              <li>HR-Window Thunder Rate: 25%</li>
              <li>Hard Hit%: 5%</li>
            </ul>
          </section>
        </div>

        <p>Adjusted xHR/BBE is the anchor because it is the most direct measure of stadium-neutral home-run-quality contact. If a hitter's batted balls are not producing expected home runs in a neutral context, the other components should not be able to fully rescue the score.</p>
        <p>HR-Window Thunder Rate measures the share of batted balls hit 105 mph or harder with launch angle between 25° and 40°. It replaces Avg Distance on Barrels as the top-end contact-shape component in LBI v1.3.</p>
      </section>

      <section class="about-section">
        <h2>Why Sweet Spot% Was Removed</h2>
        <p>Earlier versions of LBI included Sweet Spot%, which measures batted balls launched between 8° and 32°. That made sense in theory, but in practice it gave too much credit for launch angle without considering velocity.</p>
        <p>A weak line drive and a crushed fly ball can both fall into the sweet-spot range. For a stat focused on home-run quality, that created the wrong incentives.</p>
        <p>LBI v1.3 keeps Sweet Spot% out of the formula. It may still appear as a reference stat, but it is not part of LBI.</p>
      </section>

      <section class="about-section">
        <h2>How Scoring Works</h2>
        <p>LBI is percentile-based and scaled like a plus stat. The median qualified hitter is centered around 100. A 90th percentile component score maps around 150 in v1.3, giving elite power hitters room to separate from the field.</p>
        <p>Scores are not capped. A monster longball profile can push well above 150.</p>
      </section>

      <section class="about-section" id="hot-dog-stand-methodology">
        <span id="hot-dog-index" aria-hidden="true"></span>
        <h2>The Hot Dog Stand</h2>
        <p>The Hot Dog Stand tracks pitchers serving up baseball's loudest home-run-quality contact.</p>
        <p>Hot Dog Index is the pitcher-facing companion to LBI. LBI measures which hitters create elite longball contact. Hot Dog Index measures which pitchers allow it. It uses Baseball Savant Home Run Tracker and Statcast batted-ball data.</p>
        <p>Hot Dog Index is a volume stat: total longball damage allowed. Cooked / 100 BBE is the rate version.</p>
        <p><strong>LBI asks who creates the longball contact. The Hot Dog Index asks who serves it up.</strong></p>

        <h3>Hot Dog Index v1.1</h3>
        <p>HDI v1.1 measures pitcher-side longball damage allowed, anchored by Adjusted xHR/BBE allowed and sharpened by HR-capable contact, no-doubters, Avg EV allowed, and HR-Window Thunder Allowed.</p>
        <p>A meatball is a Heart-zone pitch thrown below the pitcher's 25th-percentile velocity for that pitch type, with a 15+ pitch sample for that pitch type. The Hot Dog Stand identifies pitchers who have served up the most damage on these mistakes.</p>
        <p>HR-Window Thunder Allowed measures 105+ mph batted balls allowed between 25° and 40°, per BBE allowed.</p>
        <p>The current v1.1 formula combines:</p>
        <ul class="about-list">
          <li><strong>Adjusted xHR/BBE allowed</strong>: 32.5%</li>
          <li><strong>HR-capable BBE rate allowed</strong>: 20%</li>
          <li><strong>No-Doubter rate allowed</strong>: 10%</li>
          <li><strong>Average exit velocity allowed</strong>: 7.5%</li>
          <li><strong>HR-Window Thunder Allowed</strong>: 30%</li>
        </ul>

        <dl class="glossary">
          <div>
            <dt>No-Doubter Allowed</dt>
            <dd>A batted ball that would clear all 30 MLB parks.</dd>
          </div>
          <div>
            <dt>Mostly Gone Allowed</dt>
            <dd>A batted ball that would clear many parks, but not all.</dd>
          </div>
          <div>
            <dt>Doubter Allowed</dt>
            <dd>A batted ball that would clear only a small number of parks.</dd>
          </div>
          <div>
            <dt>HR-Capable BBE</dt>
            <dd>A batted ball classified as having home-run potential in at least one MLB park.</dd>
          </div>
        </dl>
      </section>

      <section class="about-section">
        <h2>Version History</h2>
        <div class="version-list">
          <section>
            <h3>v1.0 Provisional</h3>
            <p>Initial contact-quality formula using Barrel%, Hard Hit%, Avg Distance on Barrels, and Sweet Spot%.</p>
          </section>
          <section>
            <h3>v1.1 Stadium-Neutral</h3>
            <p>Added Baseball Savant Adjusted xHR/BBE.</p>
          </section>
          <section>
            <h3>v1.2</h3>
            <p>Made Adjusted xHR/BBE the structural anchor, removed Sweet Spot%, and widened the scale to better reflect the spread of true longball skill.</p>
          </section>
          <section>
            <h3>v1.3</h3>
            <p>Replaced Avg Distance on Barrels with HR-Window Thunder Rate, using 105+ mph contact launched between 25° and 40° to better isolate home-run-shaped damage.</p>
          </section>
        </div>
      </section>

      <section class="about-section">
        <h2>Feature Glossary</h2>
        <dl class="glossary">
          <div id="jacked-up">
            <dt>Jacked Up</dt>
            <dd>The farthest home runs in the current Statcast sample.</dd>
          </div>
          <div id="lbi-leaders">
            <dt>LBI Leaders</dt>
            <dd>The hitters producing the best stadium-neutral home-run-quality contact.</dd>
          </div>
          <div id="cheapies">
            <dt>Cheapies</dt>
            <dd>Actual home runs classified as Doubters, meaning they would clear only 1-7 MLB parks.</dd>
          </div>
          <div id="pull-air-juice">
            <dt>Pull-Air Juice</dt>
            <dd>Pulled-air balls hit 105+ mph per 100 PA. It is a context stat, not currently part of LBI.</dd>
          </div>
          <div id="daily-dong">
            <dt>Daily Dong</dt>
            <dd>The loudest or most impressive actual home run from the latest available game date.</dd>
          </div>
          <div id="hot-dog-robbery">
            <dt>Hot Dog Robbery</dt>
            <dd>The best HR-capable batted ball from the latest available game date that did not become an actual home run.</dd>
          </div>
          <div id="cheapest-dong">
            <dt>Cheapest Dong</dt>
            <dd>The flimsiest actual home run from the latest available game date, preferably a Doubter.</dd>
          </div>
          <div id="hr-capable-bbe">
            <dt>HR-capable BBE</dt>
            <dd>A batted ball classified by Savant as having home-run potential in at least one MLB park.</dd>
          </div>
          <div id="hot-dog-stand">
            <dt>The Hot Dog Stand</dt>
            <dd>A pitcher-accountability section built around loud, home-run-quality contact allowed.</dd>
          </div>
          <div id="hot-dog-index-glossary">
            <dt>Hot Dog Index</dt>
            <dd>A plus-style score for pitchers serving up HR-capable contact, no-doubters, and high-impact home runs.</dd>
          </div>
        </dl>
      </section>

      <section class="about-section">
        <h2>Where the Data Comes From</h2>
        <p>LBI is built on Baseball Savant's public Statcast data, accessed via the pybaseball library. The Adjusted xHR/BBE component uses Savant's Home Run Tracker, which evaluates every batted ball against all 30 MLB park dimensions and applies Savant's park-factor model for temperature, altitude, and environmental conditions. Data refreshes daily after the previous day's games.</p>
        <ul class="about-list doc-links">
          <li><a href="/docs/data-dictionary.md">Data dictionary</a></li>
          <li><a href="/docs/longball-index-methodology.md">Longball Index methodology</a></li>
          <li><a href="/docs/hot-dog-index-methodology.md">Hot Dog Index methodology</a></li>
          <li><a href="/llms.txt">AI-readable site summary</a></li>
        </ul>
      </section>

      <section class="about-section about-section--credit">
        <h2>Credits / Data Source</h2>
        <p>Data is derived from public Statcast and Baseball Savant data. The Long Ball is an independent project and is not affiliated with Major League Baseball or Baseball Savant.</p>
        <a class="back-link" href="${ROUTES.home}">Back to leaderboard</a>
      </section>
    </article>
  `;
}

function renderHotDogPage() {
  const rows = getVisibleHotDogRows();

  return `
    <section class="about-hero hot-dog-page-hero">
      ${renderSiteNav('hot-dog')}
      <p class="eyebrow hot-dog-eyebrow">Pitcher Accountability</p>
      <h1 class="hot-dog-title-lockup"><span class="hot-dog-title-icon" aria-hidden="true"></span><span>HOT DOG STAND</span></h1>
      <p class="tagline">Who's serving it up.</p>
      <p class="hot-dog-page-copy">
        The flip side of the Longball Index &mdash; pitchers ranked by the loudest contact they've allowed.
      </p>
      <a class="back-link" href="${getConceptUrl('hot-dog-stand-methodology')}">Methodology →</a>
    </section>

    <div id="hot-dog-story-slot">
      ${renderHotDogStoryCards(state.hotDogPitchers)}
      ${renderDailyFeatureStrip('pitcher')}
    </div>

    ${renderHotDogControls()}

    <section class="leaderboard hot-dog-leaderboard" aria-live="polite">
      <div class="section-heading">
        <h2>Hot Dog Index leaderboard</h2>
      </div>
      <div id="hot-dog-leaderboard-content">
        ${renderHotDogLeaderboardContent(rows)}
      </div>
    </section>
    <div id="pitcher-detail-slot">
      ${renderPitcherDetailModal()}
    </div>
  `;
}

function renderEmptyState() {
  return `
    <section class="message">
      <h2>No matching hitters</h2>
      <p>Try a broader search or lower the minimum home-run filter.</p>
    </section>
  `;
}

function renderError() {
  const dataUrl = state.selectedSeason === CURRENT_SEASON ? DATA_URL : getSeasonDataUrl(state.selectedSeason);
  return `
    <section class="message error">
      <h2>Leaderboard unavailable</h2>
      <p>${escapeHtml(state.error)}</p>
      <p>Run the Python data script and confirm that <code>${dataUrl}</code> contains player rows.</p>
    </section>
  `;
}

function renderLeaderboardContent(rows) {
  return `
    ${state.status === 'loading' ? '<section class="message"><h2>Loading leaderboard...</h2></section>' : ''}
    ${state.status === 'error' ? renderError() : ''}
    ${state.status === 'ready' && state.selectedSeason !== CURRENT_SEASON ? `
      <p class="historical-note">Historical leaderboards are calculated retroactively using current LBI v1.3 methodology.</p>
    ` : ''}
    ${state.status === 'ready' && rows.length > 0 ? renderTable(rows) : ''}
    ${state.status === 'ready' && rows.length === 0 ? renderEmptyState() : ''}
  `;
}

function renderHotDogLeaderboardContent(rows) {
  return `
    ${state.hotDogStatus === 'loading' ? '<section class="message"><h2>Loading Hot Dog Stand...</h2></section>' : ''}
    ${state.hotDogStatus === 'error' ? `
      <section class="message error">
        <h2>Hot Dog Stand unavailable</h2>
        <p>${escapeHtml(state.hotDogError)}</p>
        <p>Run the Python data script and confirm that <code>${HOT_DOG_URL}</code> contains pitcher rows.</p>
      </section>
    ` : ''}
    ${state.hotDogStatus === 'ready' && rows.length > 0 ? renderHotDogTable(rows) : ''}
    ${state.hotDogStatus === 'ready' && rows.length === 0 ? `
      <section class="message">
        <h2>No matching pitchers</h2>
        <p>Try a broader search or lower the HR-capable BBE filter.</p>
      </section>
    ` : ''}
  `;
}

function updateReadySections() {
  const rows = getVisibleRows();
  const featureSlot = document.querySelector('#feature-slot');
  const leaderboardContent = document.querySelector('#leaderboard-content');

  if (featureSlot) {
    featureSlot.innerHTML = state.status === 'ready' ? renderFeatureCards(state.rows) : '';
  }

  if (leaderboardContent) {
    leaderboardContent.innerHTML = renderLeaderboardContent(rows);
    bindSortEvents();
    bindPlayerRowEvents();
  }

  updatePlayerDetailModal();
}

function updatePlayerDetailModal() {
  const detailSlot = document.querySelector('#player-detail-slot');

  if (detailSlot) {
    detailSlot.innerHTML = renderPlayerDetailModal();
    bindPlayerDetailEvents();
  }
}

function updateHotDogPageContent() {
  const rows = getVisibleHotDogRows();
  const hotDogContent = document.querySelector('#hot-dog-leaderboard-content');

  if (hotDogContent) {
    hotDogContent.innerHTML = renderHotDogLeaderboardContent(rows);
    bindHotDogSortEvents();
    bindPitcherRowEvents();
  }

  updatePitcherDetailModal();
}

function updateHotDogSection() {
  const hotDogSlot = document.querySelector('#hot-dog-slot');

  if (hotDogSlot) {
    hotDogSlot.innerHTML = renderHotDogSection(state.hotDogPitchers);
  }

  const hotDogStorySlot = document.querySelector('#hot-dog-story-slot');

  if (hotDogStorySlot) {
    hotDogStorySlot.innerHTML = renderHotDogStoryCards(state.hotDogPitchers);
  }

  updateHotDogPageContent();
}

function bindControlEvents() {
  document.querySelector('#search-input')?.addEventListener('input', (event) => {
    state.query = event.target.value;
    updateReadySections();
  });

  document.querySelector('#min-hr-select')?.addEventListener('change', (event) => {
    state.minHr = Number(event.target.value);
    updateReadySections();
  });

  document.querySelector('#season-select')?.addEventListener('change', (event) => {
    state.query = '';
    state.selectedPlayerId = null;
    loadLeaderboard(Number(event.target.value));
  });
}

function bindHotDogControlEvents() {
  document.querySelector('#hot-dog-search-input')?.addEventListener('input', (event) => {
    state.hotDogQuery = event.target.value;
    updateHotDogPageContent();
  });

  document.querySelector('#hot-dog-min-select')?.addEventListener('change', (event) => {
    state.hotDogMinHrCapable = Number(event.target.value);
    updateHotDogPageContent();
  });

  document.querySelector('#hot-dog-role-select')?.addEventListener('change', (event) => {
    state.hotDogRole = event.target.value;
    updateHotDogPageContent();
  });
}

function bindSortEvents() {
  document.querySelectorAll('[data-sort-key]').forEach((button) => {
    button.addEventListener('click', () => {
      const nextKey = button.dataset.sortKey;

      if (state.sortKey === nextKey) {
        state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
      } else {
        state.sortKey = nextKey;
        state.sortDirection = columns.find((column) => column.key === nextKey)?.numeric ? 'desc' : 'asc';
      }

      updateReadySections();
    });
  });
}

function closePlayerDetail() {
  state.selectedPlayerId = null;
  updatePlayerDetailModal();
}

function closePitcherDetail() {
  state.selectedPitcherId = null;
  updatePitcherDetailModal();
}

function bindPlayerRowEvents() {
  document.querySelectorAll('[data-player-id]').forEach((row) => {
    const openDetail = () => {
      state.selectedPlayerId = Number(row.dataset.playerId);
      updatePlayerDetailModal();
    };

    row.addEventListener('click', openDetail);
    row.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openDetail();
      }
    });
  });
}

function bindPlayerDetailEvents() {
  document.querySelector('[data-detail-close]')?.addEventListener('click', closePlayerDetail);
  document.querySelector('[data-detail-backdrop]')?.addEventListener('click', (event) => {
    if (event.target === event.currentTarget) {
      closePlayerDetail();
    }
  });
}

function bindPitcherRowEvents() {
  document.querySelectorAll('[data-pitcher-id]').forEach((row) => {
    const openDetail = () => {
      state.selectedPitcherId = Number(row.dataset.pitcherId);
      updatePitcherDetailModal();
    };

    row.addEventListener('click', openDetail);
    row.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openDetail();
      }
    });
  });
}

function bindPitcherDetailEvents() {
  document.querySelector('[data-pitcher-detail-close]')?.addEventListener('click', closePitcherDetail);
  document.querySelector('[data-pitcher-detail-backdrop]')?.addEventListener('click', (event) => {
    if (event.target === event.currentTarget) {
      closePitcherDetail();
    }
  });
}

function updatePitcherDetailModal() {
  const detailSlot = document.querySelector('#pitcher-detail-slot');

  if (detailSlot) {
    detailSlot.innerHTML = renderPitcherDetailModal();
    bindPitcherDetailEvents();
  }
}

function bindHotDogSortEvents() {
  document.querySelectorAll('[data-hot-dog-sort-key]').forEach((button) => {
    button.addEventListener('click', () => {
      const nextKey = button.dataset.hotDogSortKey;

      if (state.hotDogSortKey === nextKey) {
        state.hotDogSortDirection = state.hotDogSortDirection === 'asc' ? 'desc' : 'asc';
      } else {
        state.hotDogSortKey = nextKey;
        state.hotDogSortDirection = hotDogColumns.find((column) => column.key === nextKey)?.numeric ? 'desc' : 'asc';
      }

      updateHotDogPageContent();
    });
  });
}

function renderSiteNav(activeView) {
  const links = [
    { href: ROUTES.home, label: 'Longball Index', view: 'home' },
    { href: ROUTES.hotDog, label: 'Hot Dog Stand', view: 'hot-dog' },
    { href: ROUTES.reports, label: 'Longball Scouting Report', view: 'reports' },
    { href: ROUTES.stackWatch, label: 'Stack Watch', view: 'stack-watch' },
    { href: ROUTES.notes, label: 'Notes', view: 'notes' },
    { href: ROUTES.about, label: 'About', view: 'about' }
  ];

  return `
    <nav class="site-nav" aria-label="Primary">
      ${links.map((link) => `
        <a href="${link.href}" ${activeView === link.view ? 'aria-current="page"' : ''}>${link.view === 'hot-dog' ? '<span class="hot-dog-nav-icon" aria-hidden="true"></span>' : ''}${link.label}</a>
      `).join('')}
    </nav>
  `;
}

function getSelectedPostSlug() {
  return getSelectedPostSlugFromLocation();
}

function getSelectedPost() {
  const selectedSlug = getSelectedPostSlug();
  return state.posts.find((post) => post.slug === selectedSlug) ?? state.posts[0] ?? null;
}

function updateArticleStructuredData(post) {
  const id = 'note-article-jsonld';
  document.getElementById(id)?.remove();

  if (!post?.structuredData) return;

  const script = document.createElement('script');
  script.id = id;
  script.type = 'application/ld+json';
  script.textContent = JSON.stringify(post.structuredData);
  document.head.appendChild(script);
}

function clearArticleStructuredData() {
  document.getElementById('note-article-jsonld')?.remove();
}

function formatPostDate(value) {
  if (!value) return '';
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' });
}

function renderNotesPage() {
  const selectedPost = getSelectedPost();

  return `
    <section class="about-hero notes-hero">
      ${renderSiteNav('notes')}
      <p class="eyebrow">Editorial</p>
      <h1>LONGBALL NOTES</h1>
      <p class="tagline">What the board is telling us.</p>
    </section>

    ${state.postsStatus === 'loading' ? '<section class="message"><h2>Loading Longball Notes...</h2></section>' : ''}
    ${state.postsStatus === 'error' ? `
      <section class="message error">
        <h2>Longball Notes unavailable</h2>
        <p>${escapeHtml(state.postsError)}</p>
      </section>
    ` : ''}
    ${state.postsStatus === 'ready' && !state.posts.length ? '<section class="message"><h2>No notes posted yet.</h2></section>' : ''}

    ${state.postsStatus === 'ready' && state.posts.length ? `
      <section class="notes-layout">
        <aside class="notes-list" aria-label="Longball Notes archive">
          <p class="eyebrow">Archive</p>
          ${state.posts.map((post) => `
            <a class="notes-list__item" href="${escapeHtml(getPostUrl(post.slug))}" ${post.slug === selectedPost?.slug ? 'aria-current="page"' : ''}>
              <strong>${escapeHtml(post.title)}</strong>
              <span>${escapeHtml(formatPostDate(post.date))}</span>
            </a>
          `).join('')}
        </aside>
        <article class="note-post">
          <header class="note-post__header">
            <p class="eyebrow">${escapeHtml(formatPostDate(selectedPost?.date))}</p>
            <h2>${escapeHtml(selectedPost?.title ?? '')}</h2>
            ${selectedPost?.description ? `<p>${escapeHtml(selectedPost.description)}</p>` : ''}
          </header>
          <div class="note-post__body">
            ${selectedPost?.html ?? ''}
          </div>
        </article>
      </section>
    ` : ''}
  `;
}

function renderHomePage() {
  const rows = getVisibleRows();

  return `
    <section class="hero">
      <div class="hero-main">
        ${renderSiteNav('home')}
        <h1>LONGBALL</h1>
        <p class="hero-title-suffix">index.</p>
        <p class="tagline">Digging the data behind the distance</p>
        <p class="hero-lbi-note">Pure home run quality, stadium-neutral. 100 = league average.</p>
      </div>
      <aside class="hero-meta">
        <strong>LBI v1.3</strong>
        <span>Pure home-run quality</span>
        <span>Stadium-neutral</span>
        <span class="hero-meta-divider" aria-hidden="true"></span>
        <span>100 = league average</span>
      </aside>
    </section>

    <div id="feature-slot">
      ${state.status === 'ready' ? renderFeatureCards(state.rows) : ''}
    </div>
    ${state.status === 'ready' ? renderDailyFeatureStrip('hitter') : ''}
    ${renderHotDogMiniCallout()}
    ${state.status === 'ready' ? renderControls() : ''}

    <section class="leaderboard" aria-live="polite">
      <div class="section-heading">
        <h2>MLB Longball Index leaderboard</h2>
      </div>
      <div id="leaderboard-content">
        ${renderLeaderboardContent(rows)}
      </div>
    </section>
    ${renderScoutingReportPromo()}
    ${renderHotDogCrossLink()}
    <div id="player-detail-slot">
      ${renderPlayerDetailModal()}
    </div>

    ${renderFutureFeatures()}
  `;
}

function render() {
  if (state.view === 'about') {
    app.innerHTML = renderAboutPage();
  } else if (state.view === 'notes') {
    app.innerHTML = renderNotesPage();
  } else if (state.view === 'hot-dog') {
    app.innerHTML = renderHotDogPage();
  } else {
    app.innerHTML = renderHomePage();
  }

  if (state.view === 'home') {
    clearArticleStructuredData();
    bindControlEvents();
    bindSortEvents();
    bindPlayerRowEvents();
    bindPlayerDetailEvents();
  } else if (state.view === 'hot-dog') {
    clearArticleStructuredData();
    bindHotDogControlEvents();
    bindHotDogSortEvents();
    bindPitcherRowEvents();
    bindPitcherDetailEvents();
  } else if (state.view === 'notes') {
    updateArticleStructuredData(getSelectedPost());
  } else {
    clearArticleStructuredData();
    const aboutAnchor = getAboutAnchor();
    if (aboutAnchor) {
      window.requestAnimationFrame(() => {
        document.getElementById(aboutAnchor)?.scrollIntoView({ block: 'start' });
      });
    }
  }
}

window.addEventListener('hashchange', () => {
  state.view = getViewFromLocation();
  state.selectedPlayerId = null;
  state.selectedPitcherId = null;
  render();
});

window.addEventListener('popstate', () => {
  state.view = getViewFromLocation();
  state.selectedPlayerId = null;
  state.selectedPitcherId = null;
  render();
});

document.addEventListener('click', handleInternalNavigation);

window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    if (state.selectedPlayerId !== null) {
      closePlayerDetail();
    }

    if (state.selectedPitcherId !== null) {
      closePitcherDetail();
    }
  }
});

render();
loadLeaderboard();
loadHotDogData();
loadPosts();
