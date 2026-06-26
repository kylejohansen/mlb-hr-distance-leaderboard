import './styles.css';

const DATA_URL = '/data/hr-distance-latest.json';
const HOT_DOG_URL = '/data/hot-dog-stand-latest.json';
const DAILY_DONG_OVERRIDES_URL = '/data/daily-dong-overrides.json';
const POSTS_URL = '/data/posts.json';
const CURRENT_SEASON = 2026;
const FRESH_WINDOW_DAYS = 10;
const LBI_SEASONS = [2026, 2025, 2024, 2023, 2022, 2021];
const LBI_LIMITED_SAMPLE_BUFFER = 18;
const MS_PER_DAY = 24 * 60 * 60 * 1000;
const TALE_OF_THE_TAPE_KEYS = ['dailyDong', 'hotDogRobbery', 'cheapestDong'];
const SURFACE_PAPER = 'var(--lb-surface-paper)';
const TEAM_BADGE_COLORS = {
  ARI: { bg: '#a71930', fg: SURFACE_PAPER, border: '#000000' },
  ATH: { bg: '#003831', fg: '#efb21e', border: '#efb21e' },
  ATL: { bg: '#13274f', fg: SURFACE_PAPER, border: '#ce1141' },
  BAL: { bg: '#df4601', fg: '#1a1a1a', border: '#1a1a1a' },
  BOS: { bg: '#bd3039', fg: SURFACE_PAPER, border: '#0c2340' },
  CHC: { bg: '#0e3386', fg: SURFACE_PAPER, border: '#cc3433' },
  CWS: { bg: '#27251f', fg: SURFACE_PAPER, border: '#c4ced4' },
  CIN: { bg: '#c6011f', fg: SURFACE_PAPER, border: '#1a1a1a' },
  CLE: { bg: '#0c2340', fg: SURFACE_PAPER, border: '#e31937' },
  COL: { bg: '#33006f', fg: SURFACE_PAPER, border: '#c4ced4' },
  DET: { bg: '#0c2340', fg: SURFACE_PAPER, border: '#fa4616' },
  HOU: { bg: '#002d62', fg: SURFACE_PAPER, border: '#eb6e1f' },
  KC: { bg: '#004687', fg: SURFACE_PAPER, border: '#bd9b60' },
  LAA: { bg: '#ba0021', fg: SURFACE_PAPER, border: '#003263' },
  LAD: { bg: '#005a9c', fg: SURFACE_PAPER, border: '#ef3e42' },
  MIA: { bg: '#00a3e0', fg: '#1a1a1a', border: '#ef3340' },
  MIL: { bg: '#12284b', fg: '#ffc52f', border: '#ffc52f' },
  MIN: { bg: '#002b5c', fg: SURFACE_PAPER, border: '#d31145' },
  NYM: { bg: '#002d72', fg: '#ff5910', border: '#ff5910' },
  NYY: { bg: '#0c2340', fg: SURFACE_PAPER, border: '#c4ced4' },
  PHI: { bg: '#e81828', fg: SURFACE_PAPER, border: '#002d72' },
  PIT: { bg: '#27251f', fg: '#fdb827', border: '#fdb827' },
  SD: { bg: '#2f241d', fg: '#ffc425', border: '#ffc425' },
  SEA: { bg: '#0c2c56', fg: SURFACE_PAPER, border: '#005c5c' },
  SF: { bg: '#fd5a1e', fg: '#1a1a1a', border: '#27251f' },
  STL: { bg: '#c41e3a', fg: SURFACE_PAPER, border: '#0c2340' },
  TB: { bg: '#092c5c', fg: '#8fbce6', border: '#f5d130' },
  TEX: { bg: '#003278', fg: SURFACE_PAPER, border: '#c0111f' },
  TOR: { bg: '#134a8e', fg: SURFACE_PAPER, border: '#e8291c' },
  WSH: { bg: '#ab0003', fg: SURFACE_PAPER, border: '#14225a' }
};

const columns = [
  { key: 'rank', label: '#', numeric: true },
  { key: 'player', label: 'Player' },
  { key: 'team', label: 'Team' },
  { key: 'longballIndex', label: 'LBI', numeric: true },
  { key: 'lbiArchetype', label: 'Type', shortLabel: 'Type' },
  { key: 'hr', label: 'HR', numeric: true },
  { key: 'barrelRate', label: 'Barrel%', shortLabel: 'Brl%', numeric: true, unit: 'percent' },
  { key: 'maxExitVelocity', label: 'MAX EV', shortLabel: 'MAX EV', numeric: true, unit: 'mph' },
  { key: 'oppoPop', label: 'OppoPop', shortLabel: 'OppoPop', subtitle: '100 = avg', numeric: true, unit: 'lbi' },
  { key: 'pullPop', label: 'Pull Pop', shortLabel: 'Pull Pop', subtitle: '100 = avg', numeric: true, unit: 'lbi' },
  { key: 'pullAirRate', label: 'Pull Air%', shortLabel: 'Pull Air%', numeric: true, unit: 'percent' }
];

const hotDogColumns = [
  { key: 'rank', label: '#', numeric: true },
  { key: 'pitcher', label: 'Pitcher' },
  { key: 'team', label: 'Team' },
  { key: 'pitcherRole', label: 'Role' },
  { key: 'hotDogIndex', label: 'Hot Dog Damage', shortLabel: 'HDD', numeric: true, unit: 'lbi' },
  {
    key: 'cookedPlus',
    label: 'Cooked',
    shortLabel: 'Cooked',
    subtitle: '100 = avg',
    numeric: true,
    unit: 'lbi'
  },
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
  lbiMinimumBbe: 0,
  lbiLimitedSampleThreshold: 120,
  query: '',
  minHr: 1,
  minBbe: 0,
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

const MODAL_OPEN_CLASS = 'modal-open';
const FEATURE_CARD_LIMIT = 5;
const HOT_DOG_COOKED_MIN_BBE_ALLOWED = 50;
const HOT_DOG_COOKED_MIN_HR_CAPABLE_BBE = 12;
let modalScrollY = 0;

const app = document.querySelector('#app');

function normalizeRow(row, index, sampleContext = {}) {
  const hr = Number(row.hr ?? row.home_runs ?? row.homeRuns);
  const xhr = row.xhr == null ? null : Number(row.xhr);
  const xhrDiff = statAvailable(xhr) && Number.isFinite(hr)
    ? xhr - hr
    : (row.xhrDiff == null ? null : Number(row.xhrDiff));
  const bbe = Number(row.bbe ?? 0);
  const limitedThreshold = Number(sampleContext.limitedThreshold ?? 120);

  return {
    batter: Number(row.batter ?? row.batter_id ?? 0),
    player: String(row.player ?? row.player_name ?? '').trim(),
    team: String(row.team ?? '').trim(),
    position: String(row.position ?? row.primaryPosition ?? row.pos ?? '').trim(),
    bbe,
    pa: Number(row.pa ?? row.plateAppearances ?? 0),
    hr,
    avgDistance: Number(row.avgDistance ?? row.avg_hr_distance ?? row.avg_distance),
    longestHr: Number(row.longestHr ?? row.longest_hr ?? row.max_distance),
    avgExitVelocity: Number(row.avgExitVelocity ?? row.avg_exit_velocity ?? row.avg_ev),
    xhr,
    xhrPerBbe: row.xhrPerBbe == null ? null : Number(row.xhrPerBbe),
    xhrDiff,
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
    maxExitVelocity: row.maxExitVelocity == null ? null : Number(row.maxExitVelocity),
    avgLaunchAngle: row.avgLaunchAngle == null ? null : Number(row.avgLaunchAngle),
    avgDistanceOnBarrels: row.avgDistanceOnBarrels == null ? null : Number(row.avgDistanceOnBarrels),
    avgLaunchAngleOnBarrels: row.avgLaunchAngleOnBarrels == null ? null : Number(row.avgLaunchAngleOnBarrels),
    pullAirRate: row.pullAirRate == null ? null : Number(row.pullAirRate),
    pulledAirBbe: row.pulledAirBbe == null ? null : Number(row.pulledAirBbe),
    oppoAirBbe: row.oppoAirBbe == null ? null : Number(row.oppoAirBbe),
    crushedPulledAirBbe: row.crushedPulledAirBbe == null ? null : Number(row.crushedPulledAirBbe),
    pullAirJuice: row.pullAirJuice == null ? null : Number(row.pullAirJuice),
    pullAirJuicePer100Pa: row.pullAirJuicePer100Pa == null ? null : Number(row.pullAirJuicePer100Pa),
    pullPop: row.pullPop == null ? null : Number(row.pullPop),
    oppoAirJuice: row.oppoAirJuice == null ? null : Number(row.oppoAirJuice),
    oppoAirJuicePer100Pa: row.oppoAirJuicePer100Pa == null ? null : Number(row.oppoAirJuicePer100Pa),
    oppoPop: row.oppoPop == null ? null : Number(row.oppoPop),
    oppoPopTier: row.oppoPopTier == null ? '' : String(row.oppoPopTier),
    oppoPopDisplayLabel: row.oppoPopDisplayLabel == null ? '' : String(row.oppoPopDisplayLabel),
    directionalPowerTag: row.directionalPowerTag == null ? '' : String(row.directionalPowerTag),
    directionalPowerNote: row.directionalPowerNote == null ? '' : String(row.directionalPowerNote),
    contactPct: row.contactPct == null ? null : Number(row.contactPct),
    contactSwings: row.contactSwings == null ? null : Number(row.contactSwings),
    contactPa: row.contactPa == null ? null : Number(row.contactPa),
    pesky: row.pesky == null ? null : Number(row.pesky),
    sweetSpotRate: Number(row.sweetSpotRate ?? 0),
    longballIndex: Number(row.longballIndex ?? 0),
    thumpIndex: row.thumpIndex == null ? null : Number(row.thumpIndex),
    improbabilityIndex: row.improbabilityIndex == null ? null : Number(row.improbabilityIndex),
    longBallEventCount: row.longBallEventCount == null ? null : Number(row.longBallEventCount),
    lbiArchetype: row.lbiArchetype == null ? '' : String(row.lbiArchetype),
    sprayDiversity: row.sprayDiversity == null ? null : Number(row.sprayDiversity),
    lbiSampleFlag: row.lbiSampleFlag == null ? '' : String(row.lbiSampleFlag),
    lbiV14OppoPct: row.lbiV14OppoPct == null ? null : Number(row.lbiV14OppoPct),
    lbiV14PullPct: row.lbiV14PullPct == null ? null : Number(row.lbiV14PullPct),
    lbiVersion: String(row.lbiVersion ?? '1.4'),
    lbiComponents: row.lbiComponents ?? {},
    sampleBadge: String(row.sampleBadge ?? 'Building Sample'),
    lbiLimitedSample: bbe > 0 && bbe < limitedThreshold,
    sourceRank: index + 1
  };
}

function getRowsFromPayload(payload) {
  const rows = Array.isArray(payload) ? payload : payload?.players;

  if (!Array.isArray(rows)) {
    throw new Error('Expected the JSON to be an array or an object with a players array.');
  }

  const minimumBbe = Number(payload?.qualifiedBy?.minimumBbe ?? 0);
  const limitedThreshold = minimumBbe > 0 ? minimumBbe + LBI_LIMITED_SAMPLE_BUFFER : 120;

  return rows.map((row, index) => normalizeRow(row, index, { limitedThreshold })).filter((row) => {
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
    gettingCookedPer100Bbe: row.gettingCookedPer100Bbe == null
      ? (row.cookedPer100Bbe == null ? null : Number(row.cookedPer100Bbe))
      : Number(row.gettingCookedPer100Bbe),
    cookedPer100Bbe: row.gettingCookedPer100Bbe == null
      ? (row.cookedPer100Bbe == null ? null : Number(row.cookedPer100Bbe))
      : Number(row.gettingCookedPer100Bbe),
    cookedPlus: row.cookedPlus == null ? null : Number(row.cookedPlus),
    legacyCooked: row.legacyCooked == null ? null : Number(row.legacyCooked),
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
    state.lbiMinimumBbe = Number(payload?.qualifiedBy?.minimumBbe ?? 0);
    state.lbiLimitedSampleThreshold = state.lbiMinimumBbe > 0
      ? state.lbiMinimumBbe + LBI_LIMITED_SAMPLE_BUFFER
      : 120;
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

function hasNumericValue(value) {
  return value != null && Number.isFinite(Number(value));
}

function compareValues(a, b, column, direction = 'asc') {
  const aValue = column.key === 'rank' ? a.sourceRank : a[column.key];
  const bValue = column.key === 'rank' ? b.sourceRank : b[column.key];

  if (column.numeric) {
    const aMissing = !hasNumericValue(aValue);
    const bMissing = !hasNumericValue(bValue);
    if (aMissing && bMissing) return 0;
    if (aMissing) return 1;
    if (bMissing) return -1;
    const base = Number(aValue) - Number(bValue);
    return direction === 'desc' ? -base : base;
  }

  return String(aValue).localeCompare(String(bValue));
}

function getLbiColumns(rows = state.rows) {
  const hasOppoPop = rows.some((row) => hasNumericValue(row.oppoPop));
  return hasOppoPop ? columns : columns.filter((column) => column.key !== 'oppoPop');
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
    .filter((row) => row.bbe >= state.minBbe)
    .filter((row) => {
      return row.player.toLowerCase().includes(query) || row.team.toLowerCase().includes(query);
    })
    .sort((a, b) => {
      const visibleColumns = getLbiColumns(state.rows);
      const column = visibleColumns.find((item) => item.key === state.sortKey)
        ?? columns.find((item) => item.key === 'longballIndex');
      const primary = compareValues(a, b, column, state.sortDirection);

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
      <label class="field field--search">
        <span>Search</span>
        <input id="search-input" type="search" placeholder="Player or team" value="${escapeHtml(state.query)}" />
      </label>
      <label class="field field--compact">
        <span>Season</span>
        <select id="season-select">
          ${LBI_SEASONS.map((season) => `
            <option value="${season}" ${state.selectedSeason === season ? 'selected' : ''}>${season}</option>
          `).join('')}
        </select>
      </label>
      <label class="field field--compact">
        <span>Minimum HR</span>
        <select id="min-hr-select">
          ${[0, 1, 3, 5, 10, 15, 20].map((value) => `
            <option value="${value}" ${state.minHr === value ? 'selected' : ''}>${value}+</option>
          `).join('')}
        </select>
      </label>
      <label class="field field--compact">
        <span>Minimum BBE</span>
        <select id="min-bbe-select">
          ${[0, 100, 150, 200, 250, 300].map((value) => `
            <option value="${value}" ${state.minBbe === value ? 'selected' : ''}>${value}+</option>
          `).join('')}
        </select>
      </label>
    </section>
  `;
}

function renderHotDogControls() {
  return `
    <section class="toolbar" aria-label="Hot Dog Stand controls">
      <label class="field field--search">
        <span>Search</span>
        <input id="hot-dog-search-input" type="search" placeholder="Pitcher or team" value="${escapeHtml(state.hotDogQuery)}" />
      </label>
      <label class="field field--compact">
        <span>Minimum HR-Capable BBE</span>
        <select id="hot-dog-min-select">
          ${[0, 3, 5, 8, 10, 15, 20].map((value) => `
            <option value="${value}" ${state.hotDogMinHrCapable === value ? 'selected' : ''}>${value}+</option>
          `).join('')}
        </select>
      </label>
      <label class="field field--compact">
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

function qualifiesForGettingCookedFeature(pitcher) {
  return pitcher.totalBbeAllowed >= HOT_DOG_COOKED_MIN_BBE_ALLOWED
    && pitcher.hrCapableBbeAllowed >= HOT_DOG_COOKED_MIN_HR_CAPABLE_BBE
    && pitcher.cookedPlus != null;
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

function renderLimitedSampleText(row, options = {}) {
  if (!row.lbiLimitedSample) return '';
  const label = options.capitalized ? 'Near floor' : 'near floor';
  return `<span class="lbi-sample-context" title="Qualified, but close to the current LBI BBE minimum.">· ${label}</span>`;
}

function renderBbeContext(row, options = {}) {
  const bbe = formatNumber(row.bbe);
  const label = options.prefix ? `BBE ${bbe}` : `${bbe} BBE`;
  return `<span class="lbi-bbe-context">${label}</span> ${renderLimitedSampleText(row, options)}`;
}

function lbiBbeContext(row) {
  return `LBI ${formatNumber(row.longballIndex, 'lbi')} · ${renderBbeContext(row, { prefix: true })}`;
}

function getTeamBadgeStyle(team) {
  const colors = TEAM_BADGE_COLORS[team];
  if (!colors) return '';
  return ` style="--team-badge-bg: ${colors.bg}; --team-badge-fg: ${colors.fg}; --team-badge-border: ${colors.border};"`;
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
        <div class="card-row__meta">${escapeHtml(row.team)} · ${lbiBbeContext(row)}</div>
      </div>
      <div class="card-row__value">${formatNumber(row.longestHr)}<span class="card-row__unit">ft</span></div>
    </li>
  `;
}

function renderIndexRow(row, rank) {
  const metaParts = [
    row.team,
    row.lbiArchetype || 'Balanced Power',
    row.pa == null ? null : `${formatNumber(row.pa)} PA`
  ].filter(Boolean);

  return `
    <li class="card-row card-row--index">
      <span class="card-row__rank">${rank}</span>
      <div class="card-row__body">
        <div class="card-row__player">${escapeHtml(row.player)}</div>
        <div class="card-row__team-code">${escapeHtml(metaParts.join(' · '))}</div>
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
    .filter(qualifiesForGettingCookedFeature)
    .sort((a, b) => {
      return b.cookedPlus - a.cookedPlus || b.hotDogIndex - a.hotDogIndex || a.pitcher.localeCompare(b.pitcher);
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
            <strong>Hot Dog Damage</strong> measures loud, home-run-quality contact allowed
            by pitchers using Baseball Savant Home Run Tracker and Statcast event data.
          </p>
        </div>
        <a class="methodology-inline-link methodology-inline-link--top" href="${ROUTES.hotDog}">View full Hot Dog Damage →</a>
      </header>

      <div class="hot-dog-grid">
        <article class="feature-card feature-card--topdog">
          <svg class="feature-card__arc" viewBox="0 0 200 60" aria-hidden="true">
            <path d="M 10 55 Q 100 -15 195 35" stroke="currentColor" stroke-width="2" fill="none" stroke-dasharray="3 3"/>
            <circle cx="195" cy="35" r="3" fill="currentColor"/>
          </svg>
          <p class="feature-card__eyebrow">WITH EXTRA MUSTARD</p>
          <h3 class="feature-card__title">HOT DOG DAMAGE</h3>
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
            <span class="feature-card__live">100 = avg</span>
          </div>
          <h3 class="feature-card__title">GETTING COOKED</h3>
          <p class="feature-card__subtitle">League-scaled premium longball damage allowed.</p>
          <ol class="feature-card__list">
            ${cooked.map((pitcher, index) => renderHotDogRow(pitcher, index + 1, {
              variant: 'cooked',
              headlineValue: formatNumber(pitcher.cookedPlus, 'lbi'),
              contextLine: `${formatNumber(pitcher.hrCapableBbeAllowed)} HR-capable BBE`
            })).join('')}
          </ol>
        </article>
      </div>
      <a class="methodology-inline-link" href="${getConceptUrl('hot-dog-stand-methodology')}">How Hot Dog Damage works →</a>
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
    .filter(qualifiesForGettingCookedFeature)
    .sort((a, b) => {
      return b.cookedPlus - a.cookedPlus || b.hotDogIndex - a.hotDogIndex || a.pitcher.localeCompare(b.pitcher);
    })
    .slice(0, 5);

  return `
    <section class="hot-dog-page-cards hot-dog-grid" aria-label="Hot Dog Stand story cards">
      <article class="feature-card feature-card--billboard-cooked">
        <div class="feature-card__topbar">
          <p class="feature-card__eyebrow">ON THE GRILL</p>
          <span class="feature-card__live">100 = avg</span>
        </div>
        <h3 class="feature-card__title">GETTING COOKED</h3>
        <p class="feature-card__subtitle">League-scaled premium longball damage allowed.</p>
        <ol class="feature-card__list">
          ${cooked.map((pitcher, index) => renderHotDogRow(pitcher, index + 1, {
            variant: 'billboard-cooked',
            headlineValue: formatNumber(pitcher.cookedPlus, 'lbi'),
            contextLine: `${formatNumber(pitcher.hrCapableBbeAllowed)} HR-capable BBE`
          })).join('')}
        </ol>
      </article>

      <article class="feature-card feature-card--billboard-damage">
        <p class="feature-card__eyebrow">WITH EXTRA MUSTARD</p>
        <h3 class="feature-card__title">HOT DOG DAMAGE</h3>
        <p class="feature-card__subtitle">Total longball damage allowed.</p>
        <ol class="feature-card__list">
          ${topDogs.map((pitcher, index) => renderHotDogRow(pitcher, index + 1, {
            variant: 'billboard-damage',
            headlineValue: formatNumber(pitcher.hotDogIndex, 'lbi'),
            contextLine: `${formatNumber(pitcher.hrCapableBbeAllowed)} HR-capable BBE`
          })).join('')}
        </ol>
      </article>

      <article class="feature-card feature-card--billboard-footlong">
        <div class="feature-card__topbar">
          <p class="feature-card__eyebrow">NO-DOUBTER DAMAGE</p>
        </div>
        <h3 class="feature-card__title">FOOTLONGS</h3>
        <p class="feature-card__subtitle">Gone everywhere.<br>Ketchup Added.</p>
        <ol class="feature-card__list">
          ${noDoubters.map((pitcher, index) => renderHotDogRow(pitcher, index + 1, {
            variant: 'billboard-footlong',
            headlineValue: formatNumber(pitcher.noDoubtersAllowed),
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
    .slice(0, FEATURE_CARD_LIMIT);
  const lbiLeaders = [...rows].sort((a, b) => b.longballIndex - a.longballIndex).slice(0, FEATURE_CARD_LIMIT);
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
    .slice(0, FEATURE_CARD_LIMIT);

  return `
    <section class="feature-grid" aria-label="The Long Ball feature modules">
      <article class="feature-card feature-card--index">
        <div class="feature-card__topbar">
          <p class="feature-card__eyebrow">THE INDEX</p>
          <span class="feature-card__live" ${updatedTitle ? `title="${escapeHtml(updatedTitle)}"` : ''}>${escapeHtml(updatedLabel)}</span>
        </div>
        <h2 class="feature-card__title">LBI LEADERS</h2>
        <p class="feature-card__subtitle">100 = avg</p>
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

function renderDailyFeatureStrip(context = 'hitter', options = {}) {
  const configs = [
    ['dailyDong', { title: 'DAILY DONG' }],
    ['hotDogRobbery', { title: 'HOT DOG ROBBERY' }],
    ['cheapestDong', { title: 'CHEAPEST DONG' }]
  ];
  const sectionClasses = [
    'daily-feature-section',
    `daily-feature-section--${context}`,
    options.compact ? 'daily-feature-section--compact' : ''
  ].filter(Boolean).join(' ');

  return `
    <section class="${sectionClasses}" aria-label="Daily longball features">
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

function columnClass(column) {
  return `col-${column.key}`;
}

function formatOptionalNumber(value, unit = '') {
  if (value == null || Number.isNaN(value)) {
    return '&mdash;';
  }

  return formatNumber(value, unit);
}

function renderLbiTableCell(row, column) {
  const className = columnClass(column);

  if (column.key === 'rank') {
    return `<td class="rank ${className}">${row.rank}</td>`;
  }

  if (column.key === 'player') {
    return `<td class="player ${className}">${escapeHtml(row.player)}</td>`;
  }

  if (column.key === 'team') {
    return `<td class="${className}"><span class="team">${escapeHtml(row.team)}</span></td>`;
  }

  if (column.key === 'longballIndex') {
    return `<td class="lbi ${className}">${formatNumber(row.longballIndex, 'lbi')}</td>`;
  }

  if (column.key === 'lbiArchetype') {
    return `<td class="${className}">${escapeHtml(row.lbiArchetype || '—')}</td>`;
  }

  return `<td class="${className}">${formatOptionalNumber(row[column.key], column.unit)}</td>`;
}

function renderTable(rows) {
  const visibleColumns = getLbiColumns(rows);

  return `
    <div class="table-shell table-shell--card-back table-shell--lbi">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              ${visibleColumns.map((column) => `
                <th scope="col" class="${columnClass(column)}">
                  <button class="sort-button" data-sort-key="${column.key}"${column.tooltip ? ` title="${escapeHtml(column.tooltip)}"` : ''}>
                    <span class="sort-button__label">
                      <span class="label-full">${column.label}</span>
                      <span class="label-short">${column.shortLabel ?? column.label}</span>
                      ${column.subtitle ? `<span class="label-subtitle">${column.subtitle}</span>` : ''}
                    </span>
                    ${renderSortIcon(column)}
                  </button>
                </th>
              `).join('')}
            </tr>
          </thead>
          <tbody>
            ${rows.map((row) => `
              <tr class="clickable-row" data-player-id="${row.batter}" tabindex="0" role="button" aria-label="Open ${escapeHtml(row.player)} detail">
                ${visibleColumns.map((column) => renderLbiTableCell(row, column)).join('')}
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function renderHotDogTable(rows) {
  return `
    <div class="table-shell table-shell--card-back table-shell--hot-dog">
      <div class="table-wrap">
        <table class="hot-dog-table">
          <thead>
            <tr>
              ${hotDogColumns.map((column) => `
                <th scope="col">
                  <button class="sort-button" data-hot-dog-sort-key="${column.key}">
                    <span class="sort-button__label">
                      <span class="label-full">${column.label}</span>
                      <span class="label-short">${column.shortLabel ?? column.label}</span>
                      ${column.subtitle ? `<span class="label-subtitle">${column.subtitle}</span>` : ''}
                    </span>
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
                <td>${formatNumber(pitcher.cookedPlus, 'lbi')}</td>
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
    </div>
  `;
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

function finiteStat(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function powerPeskyExtent() {
  const rows = state.rows.filter((row) => finiteStat(row.longballIndex) != null && finiteStat(row.pesky) != null);
  const lbiValues = rows.map((row) => Number(row.longballIndex));
  const peskyValues = rows.map((row) => Number(row.pesky));

  const extent = (values, fallback) => {
    if (!values.length) return fallback;
    const rawMin = Math.min(...values, 100);
    const rawMax = Math.max(...values, 100);
    const spread = Math.max(rawMax - rawMin, 1);
    const pad = spread * 0.07;
    return {
      min: rawMin - pad,
      max: rawMax + pad
    };
  };

  return {
    lbi: extent(lbiValues, { min: 20, max: 190 }),
    pesky: extent(peskyValues, { min: 74, max: 121 })
  };
}

function scaleToRange(value, min, max, start, end) {
  const clamped = Math.max(min, Math.min(max, Number(value)));
  return start + ((clamped - min) / (max - min)) * (end - start);
}

function powerPeskyRead(lbi, pesky) {
  if (lbi >= 100 && pesky >= 100) return 'Complete hitter';
  if (lbi >= 100 && pesky < 100) return 'Boom-or-bust';
  if (lbi < 100 && pesky >= 100) return 'Pesky contact';
  return 'Struggling';
}

function renderPowerPeskyQuadrant(player) {
  const lbi = finiteStat(player.longballIndex);
  const pesky = finiteStat(player.pesky);

  if (lbi == null || pesky == null) {
    return `
      <section class="power-pesky-quadrant power-pesky-quadrant--empty">
        <div>
          <h3>Power × Pesky</h3>
          <p>LBI and contact context</p>
        </div>
        <div class="power-pesky-quadrant__empty">Pesky context is not available for this file yet.</div>
      </section>
    `;
  }

  const extent = powerPeskyExtent();
  const plot = { left: 32, right: 340, top: 17, bottom: 108 };
  const x = scaleToRange(lbi, extent.lbi.min, extent.lbi.max, plot.left, plot.right);
  const y = scaleToRange(pesky, extent.pesky.min, extent.pesky.max, plot.bottom, plot.top);
  const x100 = scaleToRange(100, extent.lbi.min, extent.lbi.max, plot.left, plot.right);
  const y100 = scaleToRange(100, extent.pesky.min, extent.pesky.max, plot.bottom, plot.top);
  const read = powerPeskyRead(lbi, pesky);

  return `
    <section class="power-pesky-quadrant" aria-label="Power and Pesky quadrant">
      <div class="power-pesky-quadrant__header">
        <div>
          <h3>Power × Pesky</h3>
          <p>${escapeHtml(read)}</p>
        </div>
        <strong>LBI ${formatNumber(lbi, 'lbi')} / Pesky ${formatNumber(pesky, 'lbi')}</strong>
      </div>
      <svg class="power-pesky-quadrant__svg" viewBox="0 0 360 126" role="img" aria-label="Power and Pesky quadrant for ${escapeHtml(player.player)}">
        <rect class="power-pesky-quadrant__frame" x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}" />
        <rect class="power-pesky-quadrant__zone power-pesky-quadrant__zone--complete" x="${x100}" y="${plot.top}" width="${plot.right - x100}" height="${y100 - plot.top}" />
        <rect class="power-pesky-quadrant__zone power-pesky-quadrant__zone--boom" x="${x100}" y="${y100}" width="${plot.right - x100}" height="${plot.bottom - y100}" />
        <rect class="power-pesky-quadrant__zone power-pesky-quadrant__zone--pesky" x="${plot.left}" y="${plot.top}" width="${x100 - plot.left}" height="${y100 - plot.top}" />
        <rect class="power-pesky-quadrant__zone power-pesky-quadrant__zone--quiet" x="${plot.left}" y="${y100}" width="${x100 - plot.left}" height="${plot.bottom - y100}" />
        <line class="power-pesky-quadrant__axis" x1="${x100}" y1="${plot.top}" x2="${x100}" y2="${plot.bottom}" />
        <line class="power-pesky-quadrant__axis" x1="${plot.left}" y1="${y100}" x2="${plot.right}" y2="${y100}" />
        <text class="power-pesky-quadrant__label power-pesky-quadrant__label--complete" x="${plot.right - 5}" y="${plot.top + 12}" text-anchor="end">Complete</text>
        <text class="power-pesky-quadrant__label power-pesky-quadrant__label--boom" x="${plot.right - 5}" y="${plot.bottom - 6}" text-anchor="end">Boom/Bust</text>
        <text class="power-pesky-quadrant__label power-pesky-quadrant__label--pesky" x="${plot.left + 5}" y="${plot.top + 12}">Pesky</text>
        <text class="power-pesky-quadrant__label power-pesky-quadrant__label--quiet" x="${plot.left + 5}" y="${plot.bottom - 6}">Struggling</text>
        <text class="power-pesky-quadrant__axis-label power-pesky-quadrant__axis-label--x" x="${plot.right}" y="122" text-anchor="end">LBI</text>
        <text class="power-pesky-quadrant__axis-label power-pesky-quadrant__axis-label--y" x="10" y="${plot.top + 3}" transform="rotate(-90 10 ${plot.top + 3})" text-anchor="end">Pesky</text>
        <circle class="power-pesky-quadrant__dot-halo" cx="${x}" cy="${y}" r="8" />
        <circle class="power-pesky-quadrant__dot" cx="${x}" cy="${y}" r="5" />
      </svg>
      <small>100 lines mark average power and average contact.</small>
    </section>
  `;
}

function renderDirectionalPower(player) {
  const pullPop = statAvailable(player.pullPop) ? Number(player.pullPop) : null;
  const oppoPop = statAvailable(player.oppoPop) ? Number(player.oppoPop) : null;
  const tag = player.directionalPowerTag || 'Directional Context';
  const note = player.directionalPowerNote || 'Directional air power is not strongly separated by field side yet.';
  const oppoLabel = player.oppoPopDisplayLabel || player.oppoPopTier || (oppoPop == null ? 'Insufficient Oppo Sample' : 'Oppo Context');
  const oppoSample = Number.isFinite(player.oppoAirBbe)
    ? `${formatNumber(player.oppoAirBbe)} oppo-air BBE`
    : 'Opposite-field sample unavailable';
  const oppoDetail = oppoPop == null
    ? oppoSample
    : `OppoPop ${formatNumber(oppoPop, 'lbi')} · ${oppoSample}`;
  const sampleClass = oppoPop == null ? ' directional-power__metric--muted' : '';

  return `
    <section class="directional-power" aria-label="Directional power">
      <div class="directional-power__header">
        <div>
          <h3>Directional Power</h3>
          <p>${escapeHtml(note)}</p>
        </div>
        <span class="directional-power__tag">${escapeHtml(tag)}</span>
      </div>
      <div class="directional-power__metrics">
        <div class="directional-power__metric">
          <span>PullPop</span>
          <strong>${formatNumber(pullPop, 'lbi')}</strong>
          <small>Pulled-air juice</small>
        </div>
        <div class="directional-power__metric${sampleClass}">
          <span>Oppo</span>
          <strong class="directional-power__tier">${escapeHtml(oppoLabel)}</strong>
          <small>${escapeHtml(oppoDetail)}</small>
        </div>
      </div>
    </section>
  `;
}

function statAvailable(value) {
  return value != null && !Number.isNaN(value);
}

function parseDateOnly(value) {
  const match = String(value ?? '').trim().match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;

  const [, year, month, day] = match;
  const yearNumber = Number(year);
  const monthNumber = Number(month);
  const dayNumber = Number(day);
  const timestamp = Date.UTC(yearNumber, monthNumber - 1, dayNumber);
  const parsed = new Date(timestamp);
  if (
    parsed.getUTCFullYear() !== yearNumber ||
    parsed.getUTCMonth() !== monthNumber - 1 ||
    parsed.getUTCDate() !== dayNumber
  ) {
    return null;
  }

  return Number.isFinite(timestamp) ? timestamp : null;
}

function getTaleOfTheTapeDate(features = state.dailyFeatures) {
  if (!features) return '';

  return [
    features.gameDate,
    ...TALE_OF_THE_TAPE_KEYS.map((key) => features[key]?.gameDate)
  ].find((value) => String(value ?? '').trim()) ?? '';
}

function hasTaleOfTheTapeEntry(features = state.dailyFeatures) {
  return Boolean(features && TALE_OF_THE_TAPE_KEYS.some((key) => features[key]));
}

function isWithinFreshWindow(dateValue, currentTime = Date.now()) {
  const timestamp = parseDateOnly(dateValue);
  if (timestamp == null) return false;

  const elapsedDays = (currentTime - timestamp) / MS_PER_DAY;
  return elapsedDays >= -1 && elapsedDays <= FRESH_WINDOW_DAYS;
}

function showTaleOfTheTape() {
  return hasTaleOfTheTapeEntry() && isWithinFreshWindow(getTaleOfTheTapeDate());
}

function renderDetailBadges(badges) {
  if (!badges.length) return '';
  return `
    <div class="scouting-card__badges" aria-label="Player context">
      ${badges.map((badge) => `<span class="scouting-badge scouting-badge--${badge.tone ?? 'neutral'}">${escapeHtml(badge.label)}</span>`).join('')}
    </div>
  `;
}

function renderHeaderBadges(badges) {
  return renderDetailBadges(badges);
}

function renderDetailStatGrid(items, className = '') {
  return `
    <div class="detail-stat-grid ${className}">
      ${items.map((item) => `
        <div class="detail-stat">
          <span>${escapeHtml(item.label)}</span>
          <strong>${item.value}</strong>
          ${item.helper || item.badge ? `
            <small class="detail-stat__subline">
              ${item.helper ? `<span>${escapeHtml(item.helper)}</span>` : ''}
              ${item.badge ? `<span class="scouting-badge scouting-badge--${item.badge.tone ?? 'neutral'}">${escapeHtml(item.badge.label)}</span>` : ''}
            </small>
          ` : ''}
        </div>
      `).join('')}
    </div>
  `;
}

function renderParkPortability(player) {
  const noDoubters = Number(player.noDoubters);
  const mostlyGone = Number(player.mostlyGone);
  const doubters = Number(player.doubters);
  if (![noDoubters, mostlyGone, doubters].every(Number.isFinite)) return '';

  const hrCapableTotal = noDoubters + mostlyGone + doubters;
  if (hrCapableTotal <= 0) return '';

  const noDoubterPct = noDoubters / hrCapableTotal;
  const mostlyGonePct = mostlyGone / hrCapableTotal;
  const doubterPct = doubters / hrCapableTotal;
  const showBar = hrCapableTotal >= 5;

  return `
    <section class="park-portability" aria-label="Park portability">
      <div class="park-portability__heading">
        <span>Park Portability</span>
      </div>
      <p class="park-portability__caption">HR-capable contact across all 30 parks.</p>
      ${showBar ? `
        <div class="park-portability__bar" aria-hidden="true">
          <span class="park-portability__segment park-portability__segment--no-doubter" style="width: ${noDoubterPct * 100}%"></span>
          <span class="park-portability__segment park-portability__segment--mostly-gone" style="width: ${mostlyGonePct * 100}%"></span>
          <span class="park-portability__segment park-portability__segment--doubter" style="width: ${doubterPct * 100}%"></span>
        </div>
      ` : ''}
      <strong class="park-portability__count">${formatNumber(hrCapableTotal)} HR-capable BBE</strong>
      <div class="park-portability__legend" aria-label="Park portability color legend">
        <span><i class="park-portability__key park-portability__key--no-doubter"></i>No-doubters (all 30)</span>
        <span><i class="park-portability__key park-portability__key--mostly-gone"></i>Mostly gone (8-29)</span>
        <span><i class="park-portability__key park-portability__key--doubter"></i>Doubters (1-7)</span>
      </div>
    </section>
  `;
}

function getHitterContext(player) {
  const xHrDiff = statAvailable(player.xhrDiff) ? player.xhrDiff : 0;
  const hasActualCheapies = Number.isFinite(player.actualDoubterHr);
  const cheapieCount = hasActualCheapies ? player.actualDoubterHr : 0;
  const cheapieRate = hasActualCheapies && player.hr > 0 ? Math.min(cheapieCount / player.hr, 1) : null;
  const hasExpectedHrGap = xHrDiff >= 1.5 && player.longballIndex >= 110 && player.hr >= 5;
  const hasShortPorchContext = player.hr >= 5 && (-xHrDiff) >= 1.5 && cheapieRate != null && cheapieRate >= 0.25 && player.longballIndex < 145;
  const taleEvents = [
    ['Daily Dong', state.dailyFeatures?.dailyDong],
    ['Tale of the Tape', state.dailyFeatures?.hotDogRobbery],
    ['Tale of the Tape', state.dailyFeatures?.cheapestDong]
  ];
  const hasTale = taleEvents.find(([, event]) => {
    return event && (Number(event.batterId) === player.batter || normalizeName(event.batter) === normalizeName(player.player));
  });
  const badges = [];
  if (hasTale) badges.push({ label: hasTale[0], tone: 'ink' });

  let why = 'Longball contact quality stands out in the current profile.';
  if (player.longballIndex >= 160 && player.hrWindowThunderRate >= 0.055) {
    why = 'Elite LBI with repeated HR-window thunder.';
  } else if (hasExpectedHrGap) {
    why = 'Expected HR is running ahead of actual HR, and LBI supports the gap.';
  } else if (hasShortPorchContext) {
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
    cheapieRate
  };
}

function renderPlayerDetailModal() {
  const player = state.rows.find((row) => row.batter === state.selectedPlayerId);
  if (!player) return '';
  const hitterContext = getHitterContext(player);
  const expectedHr = statAvailable(player.xhr) ? player.xhr : (statAvailable(player.xhrDiff) ? player.hr + player.xhrDiff : null);
  const xHrDiffValue = statAvailable(expectedHr) ? expectedHr - player.hr : null;
  let expectedHrSubtext = '';
  if (statAvailable(xHrDiffValue)) {
    if (xHrDiffValue >= 0.05) {
      expectedHrSubtext = `+${formatNumber(xHrDiffValue, 'lbi')} vs actual`;
    } else if (xHrDiffValue <= -0.05) {
      expectedHrSubtext = `${formatNumber(Math.abs(xHrDiffValue), 'lbi')} HR above xHR`;
    } else {
      expectedHrSubtext = 'In line with actual';
    }
  }
  const pullPopValue = player.pullPop == null
    ? 'N/A'
    : formatNumber(player.pullPop, 'lbi');
  const meta = [player.team, player.position].filter(Boolean).join(' · ') || '—';

  return `
    <div class="modal-backdrop" data-detail-backdrop>
      <section class="player-modal scouting-card" role="dialog" aria-modal="true" aria-labelledby="player-detail-title" tabindex="-1">
        <button class="modal-close" type="button" data-detail-close aria-label="Close player detail">×</button>
        <header class="topps-hero-card" aria-label="Long Ball Scouting Card hero">
          <div class="topps-hero-card__masthead">
            <p class="eyebrow">Long Ball Scouting Card</p>
            ${player.team ? `<span class="topps-hero-card__team-badge topps-hero-card__team-badge--circle"${getTeamBadgeStyle(player.team)}>${escapeHtml(player.team)}</span>` : ''}
          </div>

          <div class="topps-hero-card__portrait">
            <section class="scouting-hero scouting-hero--hitter" aria-label="Hero stat">
              <div>
                <span>LBI</span>
                <strong>${formatNumber(player.longballIndex, 'lbi')}</strong>
              </div>
              <p class="scouting-hero__meta">
                <span>Rank ${formatNumber(player.sourceRank)}</span>
                <span>${renderBbeContext(player, { prefix: true })}</span>
                <span>${escapeHtml(player.lbiArchetype || 'Balanced Power')}</span>
              </p>
            </section>

            ${renderParkPortability(player)}
          </div>

          <div class="topps-hero-card__nameplate">
            <h2 id="player-detail-title">${escapeHtml(player.player)}</h2>
            <p class="player-modal__team">${escapeHtml(meta)}</p>
          </div>

          ${renderHeaderBadges(hitterContext.badges)}
        </header>

        ${renderPowerPeskyQuadrant(player)}
        ${renderDirectionalPower(player)}

        <section class="scouting-section" aria-label="Key hitter stats">
          <h3>Key Stats</h3>
          ${renderDetailStatGrid([
            { label: 'HR', value: formatNumber(player.hr) },
            {
              label: 'Thump',
              value: formatNumber(player.thumpIndex, 'lbi'),
              helper: 'Authority per PA · 100 = average'
            },
            {
              label: 'Artistry',
              value: formatNumber(player.improbabilityIndex, 'lbi'),
              helper: 'Route difficulty · 100 = average'
            },
            { label: 'Long-Ball Events', value: formatNumber(player.longBallEventCount) },
            { label: 'Oppo Long Balls', value: formatNumber(player.lbiV14OppoPct, 'percent') },
            { label: 'Pull Pop', value: pullPopValue, helper: 'Pulled air, 100+ mph · 100\u00a0=\u00a0average' },
            { label: 'Avg HR Distance', value: formatNumber(player.avgDistance, 'ft') }
          ])}
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
  const cookedRank = [...state.hotDogPitchers]
    .filter((row) => statAvailable(row.cookedPlus) && qualifiesForGettingCookedFeature(row))
    .sort((a, b) => b.cookedPlus - a.cookedPlus || a.pitcher.localeCompare(b.pitcher))
    .findIndex((row) => row.pitcherId === pitcher.pitcherId) + 1;
  const gettingCookedBadge = (pitcher.cookedPlus >= 125) || (cookedRank > 0 && cookedRank <= 15);
  if (gettingCookedBadge) badges.push({ label: 'Getting Cooked', tone: 'mustard' });
  if (statAvailable(pitcher.stackWatchScore)) badges.push({ label: 'Stack Watch', tone: 'red' });
  if (limitedSample) badges.push({ label: 'Limited Sample', tone: 'muted' });

  let why = 'Pitcher-side longball damage is showing up in the allowed-contact profile.';
  if (limitedSample && gettingCookedBadge) {
    why = 'Premium longball damage rate is elevated, but the sample is limited.';
  } else if (pitcher.hrWindowThunderRateAllowed >= 0.045) {
    why = 'HR-window thunder allowed is carrying the profile.';
  } else if (pitcher.hotDogIndex >= 135 && gettingCookedBadge) {
    why = 'Damage rate and Hot Dog Damage are both flashing.';
  } else if (pitcher.hotDogIndex >= 135) {
    why = 'Hot Dog Damage backs the longball damage.';
  } else if (pitcher.noDoubterRateAllowed >= 0.01 && pitcher.hrCapableBbeRateAllowed >= 0.14) {
    why = 'Premium contact allowed: no-doubter damage and HR-capable contact are both flashing.';
  } else if (gettingCookedBadge) {
    why = 'Premium damage rate is the main warning light.';
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
      <section class="player-modal player-modal--pitcher scouting-card" role="dialog" aria-modal="true" aria-labelledby="pitcher-detail-title" tabindex="-1">
        <button class="modal-close" type="button" data-pitcher-detail-close aria-label="Close pitcher detail">×</button>
        <header class="scouting-card__header">
          <p class="eyebrow hot-dog-eyebrow">Hot Dog Scouting Card</p>
          <h2 id="pitcher-detail-title">${escapeHtml(pitcher.pitcher)}</h2>
          <p class="player-modal__team">${escapeHtml(pitcher.team || '—')}${escapeHtml(roleMeta)}</p>
          ${renderDetailBadges(context.badges)}
        </header>

        <section class="scouting-hero scouting-hero--pitcher" aria-label="Hero stat">
          <div>
            <span>HDD</span>
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
            { label: 'HDD', value: formatNumber(pitcher.hotDogIndex, 'lbi') },
            {
              label: 'Getting Cooked',
              value: formatNumber(pitcher.cookedPlus, 'lbi'),
              helper: 'Premium longball damage allowed. 100 = average.'
            },
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
      <article class="future-tease" aria-label="Storm Watch preview">
        <div>
          <span class="future-tease__status">in development</span>
          <h3>Storm Watch</h3>
          <p>The surge detector. Catch the breakout before your league does.</p>
        </div>
      </article>
    </section>
  `;
}

function renderHotDogCrossLink() {
  return `
    <section class="hot-dog-crosslink bottom-crosslink" aria-label="Hot Dog Stand cross-link">
      <div>
        <h2>Looking for pitcher accountability?</h2>
        <p>The Hot Dog Stand tracks who's serving up baseball's loudest contact.</p>
      </div>
      <a class="methodology-inline-link" href="${ROUTES.hotDog}">View The Hot Dog Stand →</a>
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
        <p>The Longball Index (LBI) measures long-ball contact quality. Stadium-neutral. All fields.</p>
      </section>

      <section class="about-section" id="longball-index">
        <h2>What Is the Longball Index?</h2>
        <p>LBI v1.4 is a descriptive, full-season, 100-is-average index of long-ball contact quality. It scores qualifying long balls from observed physics and describes what happened, not what should happen next.</p>
        <p>The new LBI rewards force, carry, and all-fields damage. It is not an expected-home-run model, and expected HR is not part of the headline score.</p>
      </section>

      <section class="about-section">
        <h2>Why Not Just Use ISO?</h2>
        <p>Maybe I'm just old school, or slow to change, but my first go-to power metric has always been ISO. Slugging minus batting average, it's simple, durable, and quickly tells you how much extra-base damage a player is producing. Crack .200 and I'm interested. A .150 guy? Ok, he can hold his own. A .250 guy, legit power. The .300 guys are unicorns. But ISO has severe limitations, baking in everything you can't separate from a hitter's swing: stadium, defense, sequencing, luck. A 340-foot fly ball can be an easy home run in Boston and a lazy flyout in Detroit.</p>
      </section>

      <section class="about-section" id="longball-index-methodology">
        <h2>LBI v1.4 Methodology</h2>
        <p>LBI v1.4 is a from-the-ground-up redefinition of long-ball contact quality. Instead of using expected home runs as the foundation, the new LBI scores qualifying long balls by how they were hit.</p>
        <ul class="about-list">
          <li><strong>Thump</strong>: how hard and far qualifying long balls were struck, accumulated per PA</li>
          <li><strong>Artistry</strong>: how rare/difficult that spray-direction × launch-angle route is among long balls, averaged per qualifying event with shrinkage</li>
          <li><strong>True spray</strong>: batter-relative, two-coordinate spray angle, switch-hitter safe</li>
          <li><strong>Archetype</strong>: Apex Power, Thumper, Specialist, or Balanced Power</li>
        </ul>

        <div class="method-grid" aria-label="LBI v1.4 weights">
          <section>
            <h3>LBI v1.4 formula</h3>
            <ul>
              <li>ThumpIndex: 50%</li>
              <li>Artistry: 50%</li>
            </ul>
          </section>
        </div>

        <p>Eligible events are airborne long balls in the legitimate over-the-fence launch-angle band: actual over-the-fence home runs, plus non-HR contact that would have cleared at least 8 of 30 parks. Weak 1-7 park contact is excluded unless it actually cleared a fence.</p>
        <p>The result is a 100-is-average rating that rewards force, carry, and all-fields damage — plus an archetype for every hitter: the Apex Power hitters who combine force with rare-route damage, the Thumpers who overwhelm with authority, the Specialists who create long balls through difficult routes, and the Balanced Power profiles who are solid across both axes.</p>
      </section>

      <section class="about-section">
        <h2>Why Sweet Spot% Was Removed</h2>
        <p>Earlier versions of LBI included Sweet Spot%, which measures batted balls launched between 8° and 32°. That made sense in theory, but in practice it gave too much credit for launch angle without considering velocity.</p>
        <p>A weak line drive and a crushed fly ball can both fall into the sweet-spot range. For a stat focused on home-run quality, that created the wrong incentives.</p>
        <p>LBI v1.4 keeps Sweet Spot% out of the formula. It may still appear as a reference stat, but it is not part of LBI.</p>
      </section>

      <section class="about-section">
        <h2>How Scoring Works</h2>
        <p>LBI is plus-scaled, not percentile-scaled. Thump and Artistry each use 100 as the qualified-player average, and the final LBI is their 50/50 blend.</p>
        <p>Scores are not capped. A monster long-ball profile can push well above 150.</p>
      </section>

      <section class="about-section" id="hot-dog-stand-methodology">
        <span id="hot-dog-index" aria-hidden="true"></span>
        <h2>The Hot Dog Stand</h2>
        <p>The Hot Dog Stand tracks pitchers serving up baseball's loudest home-run-quality contact.</p>
        <p>Hot Dog Damage is the pitcher-facing companion to LBI. LBI measures which hitters create elite longball contact. Hot Dog Damage measures which pitchers allow it. It uses Baseball Savant Home Run Tracker and Statcast batted-ball data.</p>
        <p>Hot Dog Damage is the broad pitcher-side volume check. Getting Cooked is its league-scaled premium longball damage-rate companion, with 100 equal to average.</p>
        <p><strong>LBI asks who creates the longball contact. Hot Dog Damage asks who serves it up.</strong></p>

        <h3>Hot Dog Damage v1.1</h3>
        <p>HDD v1.1 measures pitcher-side longball damage allowed, anchored by Adjusted xHR/BBE allowed and sharpened by HR-capable contact, no-doubters, Avg EV allowed, and HR-Window Thunder Allowed.</p>
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
          <section>
            <h3>v1.4</h3>
            <p>Rebuilt LBI around observed long-ball events: Thump for force and carry, Artistry for all-fields and rare-trajectory damage.</p>
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
            <dd>The hitters producing the best long-ball contact quality: stadium-neutral, all fields.</dd>
          </div>
          <div id="cheapies">
            <dt>Cheapies</dt>
            <dd>Actual home runs classified as Doubters, meaning they would clear only 1-7 MLB parks.</dd>
          </div>
          <div id="pull-pop">
            <dt>Pull Pop</dt>
            <dd>Pulled-air contact, plus-scaled so 100 equals league average. It is a context stat, not currently part of LBI.</dd>
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
            <dt>Hot Dog Damage</dt>
            <dd>A total longball-damage score for pitchers serving up HR-capable contact, no-doubters, and high-impact home runs.</dd>
          </div>
        </dl>
      </section>

      <section class="about-section">
        <h2>Where the Data Comes From</h2>
        <p>LBI is built on Baseball Savant's public Statcast data, accessed via the pybaseball library. LBI v1.4 uses observed batted-ball physics, true two-coordinate spray, and standard park-count geometry. Adjusted xHR remains available as context, but it is not part of the LBI score. Data refreshes daily after the previous day's games.</p>
        <ul class="about-list doc-links">
          <li><a href="/docs/data-dictionary.md">Data dictionary</a></li>
          <li><a href="/docs/longball-index-methodology.md">Longball Index methodology</a></li>
          <li><a href="/docs/hot-dog-index-methodology.md">Hot Dog Damage methodology</a></li>
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
        <h2>Hot Dog Damage leaderboard</h2>
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
      <p>Try a broader search or lower the home-run or BBE filters.</p>
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
      <p class="historical-note">Historical leaderboards are calculated retroactively using current LBI v1.4 methodology.</p>
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
    detailSlot.querySelector('.player-modal')?.focus({ preventScroll: true });
  }
  syncModalScrollLock();
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

  document.querySelector('#min-bbe-select')?.addEventListener('change', (event) => {
    state.minBbe = Number(event.target.value);
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
    detailSlot.querySelector('.player-modal')?.focus({ preventScroll: true });
  }
  syncModalScrollLock();
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

function syncModalScrollLock() {
  const shouldLock = state.selectedPlayerId !== null || state.selectedPitcherId !== null;
  const isLocked = document.body.classList.contains(MODAL_OPEN_CLASS);

  if (shouldLock && !isLocked) {
    modalScrollY = window.scrollY || document.documentElement.scrollTop || 0;
    document.body.style.top = `-${modalScrollY}px`;
    document.body.classList.add(MODAL_OPEN_CLASS);
    return;
  }

  if (!shouldLock && isLocked) {
    document.body.classList.remove(MODAL_OPEN_CLASS);
    document.body.style.top = '';
    window.scrollTo(0, modalScrollY);
    modalScrollY = 0;
  }
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
      </div>
      <aside class="hero-meta">
        <strong>LBI v1.4</strong>
        <span>Long-ball contact quality</span>
        <span>Stadium-neutral</span>
        <span>All fields</span>
        <span class="hero-meta-divider" aria-hidden="true"></span>
        <span>100 = league average</span>
      </aside>
    </section>

    <div id="feature-slot">
      ${state.status === 'ready' ? renderFeatureCards(state.rows) : ''}
    </div>
    ${state.status === 'ready' && showTaleOfTheTape() ? renderDailyFeatureStrip('hitter', { compact: true }) : ''}
    ${state.status === 'ready' ? renderControls() : ''}

    <section class="leaderboard" aria-live="polite">
      <div class="section-heading">
        <h2>MLB Longball Index leaderboard</h2>
      </div>
      <div id="leaderboard-content">
        ${renderLeaderboardContent(rows)}
      </div>
    </section>
    ${renderHotDogMiniCallout()}
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

  syncModalScrollLock();
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
