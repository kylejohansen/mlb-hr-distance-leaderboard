import './styles.css';

const DATA_URL = '/data/hr-distance-latest.json';
const HOT_DOG_URL = '/data/hot-dog-stand-latest.json';

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
  { key: 'sweetSpotRate', label: 'Sweet Spot% (ref)', numeric: true, unit: 'percent' }
];

const state = {
  rows: [],
  generatedAt: '',
  query: '',
  minHr: 1,
  sortKey: 'longballIndex',
  sortDirection: 'desc',
  status: 'loading',
  error: '',
  hotDogPitchers: [],
  hotDogGeneratedAt: '',
  hotDogStatus: 'loading',
  hotDogError: '',
  view: window.location.hash === '#about' ? 'about' : 'home'
};

const app = document.querySelector('#app');

function normalizeRow(row, index) {
  return {
    player: String(row.player ?? row.player_name ?? '').trim(),
    team: String(row.team ?? '').trim(),
    bbe: Number(row.bbe ?? 0),
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
    noDoubterRate: row.noDoubterRate == null ? null : Number(row.noDoubterRate),
    barrelRate: Number(row.barrelRate ?? 0),
    hardHitRate: Number(row.hardHitRate ?? 0),
    avgDistanceOnBarrels: row.avgDistanceOnBarrels == null ? null : Number(row.avgDistanceOnBarrels),
    sweetSpotRate: Number(row.sweetSpotRate ?? 0),
    longballIndex: Number(row.longballIndex ?? 0),
    lbiVersion: String(row.lbiVersion ?? '1.2'),
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

function normalizeHotDogRow(row) {
  return {
    pitcherId: Number(row.pitcherId ?? row.pitcher_id ?? row.player_id ?? 0),
    pitcher: String(row.pitcher ?? row.pitcher_name ?? row.player_name ?? '').trim(),
    team: String(row.team ?? '').trim(),
    hotDogIndex: row.hotDogIndex == null ? null : Number(row.hotDogIndex),
    bbeAllowed: Number(row.bbeAllowed ?? row.bbe_allowed ?? 0),
    hrsAllowed: Number(row.hrsAllowed ?? row.hrs_allowed ?? row.hr_total ?? 0),
    adjustedXhrAllowed: row.adjustedXhrAllowed == null ? null : Number(row.adjustedXhrAllowed),
    adjustedXhrPerBbeAllowed: row.adjustedXhrPerBbeAllowed == null ? null : Number(row.adjustedXhrPerBbeAllowed),
    xhrDiffAllowed: row.xhrDiffAllowed == null ? null : Number(row.xhrDiffAllowed),
    hrCapableBbeAllowed: Number(row.hrCapableBbeAllowed ?? row.hr_capable_bbe_allowed ?? 0),
    hrCapableBbeRateAllowed: row.hrCapableBbeRateAllowed == null ? null : Number(row.hrCapableBbeRateAllowed),
    noDoubtersAllowed: Number(row.noDoubtersAllowed ?? row.no_doubters_allowed ?? 0),
    mostlyGoneAllowed: Number(row.mostlyGoneAllowed ?? row.mostly_gone_allowed ?? 0),
    doubtersAllowed: Number(row.doubtersAllowed ?? row.doubters_allowed ?? 0),
    noDoubterRateAllowed: row.noDoubterRateAllowed == null ? null : Number(row.noDoubterRateAllowed),
    avgExitVelocityAllowed: row.avgExitVelocityAllowed == null ? null : Number(row.avgExitVelocityAllowed),
    avgDistanceAllowed: row.avgDistanceAllowed == null ? null : Number(row.avgDistanceAllowed),
    maxExitVelocityAllowed: row.maxExitVelocityAllowed == null ? null : Number(row.maxExitVelocityAllowed),
    maxDistanceAllowed: row.maxDistanceAllowed == null ? null : Number(row.maxDistanceAllowed),
    worstServedEvent: row.worstServedEvent ?? null
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

async function loadLeaderboard() {
  try {
    const response = await fetch(DATA_URL, { cache: 'no-store' });

    if (!response.ok) {
      throw new Error(`Could not load ${DATA_URL} (${response.status}).`);
    }

    const payload = await response.json();
    const rows = getRowsFromPayload(payload);

    if (rows.length === 0) {
      throw new Error('The data file loaded, but it did not contain any valid player rows.');
    }

    state.rows = rows;
    state.generatedAt = String(payload?.generatedAt ?? '');
    state.status = 'ready';
  } catch (error) {
    state.status = 'error';
    state.error = error instanceof Error ? error.message : 'The leaderboard could not be loaded.';
  }

  render();
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

function renderSortIcon(column) {
  if (state.sortKey !== column.key) return '<span class="sort-icon inactive">↕</span>';
  return `<span class="sort-icon active">${state.sortDirection === 'asc' ? '↑' : '↓'}</span>`;
}

function renderControls() {
  return `
    <section class="toolbar" aria-label="Leaderboard controls">
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

function getPotentialHrBalls(row) {
  return Number(row.doubters ?? 0) + Number(row.mostlyGone ?? 0) + Number(row.noDoubters ?? 0);
}

function getDoubterRate(row) {
  const potentialHrBalls = getPotentialHrBalls(row);
  if (!potentialHrBalls) return 0;
  return Math.min(row.doubters / potentialHrBalls, 1);
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
        <ul class="card-row__stats">
          <li>${formatNumber(row.barrelRate, 'percent')} brl</li>
          <li>${formatNumber(row.bbe)} BBE</li>
        </ul>
      </div>
      <div class="card-row__lbi">${formatNumber(row.longballIndex, 'lbi')}</div>
    </li>
  `;
}

function renderCheapieRow(row, rank) {
  const potentialHrBalls = getPotentialHrBalls(row);
  return `
    <li class="card-row card-row--cheapie">
      <span class="card-row__rank">${rank}</span>
      <div class="card-row__body">
        <div class="card-row__player">${escapeHtml(row.player)}</div>
        <div class="card-row__meta">${escapeHtml(row.team)} · ${formatNumber(row.doubters)} of ${formatNumber(potentialHrBalls)} HR-capable</div>
      </div>
      <div class="card-row__value card-row__value--muted">${formatNumber(getDoubterRate(row), 'percent')}</div>
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
    .filter((pitcher) => pitcher.maxExitVelocityAllowed != null)
    .sort((a, b) => {
      return b.maxExitVelocityAllowed - a.maxExitVelocityAllowed || b.maxDistanceAllowed - a.maxDistanceAllowed || a.pitcher.localeCompare(b.pitcher);
    })
    .slice(0, 4);

  return `
    <section class="hot-dog-section" aria-label="The Hot Dog Stand">
      <svg class="hot-dog-divider" viewBox="0 0 1200 8" preserveAspectRatio="none" aria-hidden="true">
        <line x1="0" y1="4" x2="1200" y2="4" stroke="currentColor" stroke-width="1.5" stroke-dasharray="4 4"/>
      </svg>
      <header class="hot-dog-header">
        <div class="hot-dog-header__main">
          <p class="hot-dog-header__eyebrow">Pitcher Accountability</p>
          <h2 class="hot-dog-header__title">The Hot Dog Stand</h2>
          <p class="hot-dog-header__tagline">With extra mustard.</p>
          <p class="hot-dog-header__explainer">
            The <strong>Hot Dog Index</strong> measures loud, home-run-quality contact allowed
            by pitchers using Baseball Savant Home Run Tracker and Statcast event data.
          </p>
        </div>
      </header>

      <div class="hot-dog-grid">
        <article class="feature-card feature-card--topdog">
          <svg class="feature-card__arc" viewBox="0 0 200 60" aria-hidden="true">
            <path d="M 10 55 Q 100 -15 195 35" stroke="currentColor" stroke-width="2" fill="none" stroke-dasharray="3 3"/>
            <circle cx="195" cy="35" r="3" fill="currentColor"/>
          </svg>
          <p class="feature-card__eyebrow">Worst Served</p>
          <h3 class="feature-card__title">Top Dogs</h3>
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
          <h3 class="feature-card__title">Footlongs</h3>
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
          <h3 class="feature-card__title">Extra Mustard</h3>
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
            <p class="feature-card__eyebrow">Smoked</p>
            <span class="feature-card__live">Max EV</span>
          </div>
          <h3 class="feature-card__title">Cooked</h3>
          <p class="feature-card__subtitle">Hardest home-run contact allowed.</p>
          <ol class="feature-card__list">
            ${cooked.map((pitcher, index) => renderHotDogRow(pitcher, index + 1, {
              variant: 'cooked',
              headlineValue: `${formatNumber(pitcher.maxExitVelocityAllowed, 'mph')}<span class="card-row__unit"></span>`,
              contextLine: `${formatNumber(pitcher.maxDistanceAllowed, 'ft')} max distance`
            })).join('')}
          </ol>
        </article>
      </div>
    </section>
  `;
}

function renderFeatureCards(rows) {
  const updatedLabel = formatRelativeTime(state.generatedAt);
  const updatedTitle = state.generatedAt;
  const jackedUp = [...rows]
    .filter((row) => row.longestHr > 0)
    .sort((a, b) => b.longestHr - a.longestHr)
    .slice(0, 4);
  const lbiLeaders = [...rows].sort((a, b) => b.longballIndex - a.longballIndex).slice(0, 4);
  const wallScrapers = [...rows]
    .filter((row) => {
      return (
        Number.isFinite(row.doubters) &&
        Number.isFinite(row.mostlyGone) &&
        Number.isFinite(row.noDoubters) &&
        getPotentialHrBalls(row) >= 5
      );
    })
    .sort((a, b) => {
      const rateDiff = getDoubterRate(b) - getDoubterRate(a);
      if (rateDiff !== 0) return rateDiff;
      return b.doubters - a.doubters;
    })
    .slice(0, 4);

  return `
    <section class="feature-grid" aria-label="The Long Ball feature modules">
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

      <article class="feature-card feature-card--cheapie">
        <p class="feature-card__eyebrow feature-card__eyebrow--warn">⚠ PARK EFFECTS ABUSED</p>
        <h2 class="feature-card__title">CHEAPIES</h2>
        <p class="feature-card__subtitle">Short porch specials.</p>
        <ol class="feature-card__list">
          ${wallScrapers.map((row, index) => renderCheapieRow(row, index + 1)).join('')}
        </ol>
      </article>
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
            <tr>
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
              <td>${formatNumber(row.sweetSpotRate, 'percent')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderFutureFeatures() {
  return `
    <section class="future">
      <h2>On deck</h2>
      <div class="future-grid">
        <span>Adjusted vs Standard Home Run Tracker toggle</span>
        <span>No-Doubter Meter</span>
        <span>Wall-Scraper Wall</span>
        <span>The Hot Dog Stand / The Daily Dog</span>
        <span>CSS launch-angle visualizer</span>
      </div>
    </section>
  `;
}

function renderAboutPage() {
  return `
    <section class="about-hero">
      <a class="brand-pill" href="#home">THELONGBALL.APP</a>
      <p class="eyebrow">About / Methodology</p>
      <h1>LONG BALL NOTES</h1>
      <p class="hero-title-suffix">methodology.</p>
      <p class="tagline">The physics behind the thunder.</p>
      <a class="back-link" href="#home">Back to leaderboard</a>
    </section>

    <article class="about-page">
      <section class="about-section about-section--intro">
        <h2>About The Long Ball</h2>
        <p>The Longball Index (LBI) measures the quality of a hitter's contact, specifically tuned to home run production.</p>
      </section>

      <section class="about-section">
        <h2>What Is the Longball Index?</h2>
        <p>LBI is a per-contact measure. It evaluates the quality of a hitter's batted balls and does not factor in how often they make contact. A hitter who barrels 20% of their batted balls but strikes out frequently can score higher than a hitter who rarely whiffs but rarely punishes the baseball. This is a deliberate choice: LBI answers "what kind of contact does this hitter produce?" not "how many home runs will this hitter hit?"</p>
        <p>Hitting metrics live in one of three layers. Layer one is results: HR, ISO, SLG, what actually happened. Layer two is expected results: xHR, xSLG, xwOBA, what should have happened given the inputs. Layer three is underlying quality: Barrel%, Exit Velocity, Hard Hit%, the physics of the swing itself, separated from outcomes and from prediction. ISO lives in layer one. xISO lives in layer two. LBI is the first composite metric purpose-built for home run quality in layer three.</p>
      </section>

      <section class="about-section">
        <h2>Why Not Just Use ISO?</h2>
        <p>Maybe I'm just old school, or slow to change, but my first go-to power metric has always been ISO. Slugging minus batting average, it's simple, durable, and quickly tells you how much extra-base damage a player is producing. Crack .200 and I'm interested. A .150 guy? Ok, he can hold his own. A .250 guy, legit power. The .300 guys are unicorns. But ISO has severe limitations, baking in everything you can't separate from a hitter's swing: stadium, defense, sequencing, luck. A 340-foot fly ball can be an easy home run in Boston and a lazy flyout in Detroit.</p>
      </section>

      <section class="about-section">
        <h2>LBI v1.2 Methodology</h2>
        <p>LBI v1.2 uses four components:</p>
        <ul class="about-list">
          <li><strong>Adjusted xHR/BBE</strong>: primary anchor</li>
          <li><strong>Barrel%</strong>: home-run-quality contact rate</li>
          <li><strong>Avg Distance on Barrels</strong>: how far the best contact travels</li>
          <li><strong>Hard Hit%</strong>: raw impact/power floor</li>
        </ul>

        <div class="method-grid" aria-label="LBI v1.2 weights">
          <section>
            <h3>10+ barrels</h3>
            <ul>
              <li>Adjusted xHR/BBE: 60%</li>
              <li>Barrel%: 20%</li>
              <li>Avg Distance on Barrels: 12.5%</li>
              <li>Hard Hit%: 7.5%</li>
            </ul>
          </section>
          <section>
            <h3>5-9 barrels</h3>
            <ul>
              <li>Adjusted xHR/BBE: 67.5%</li>
              <li>Barrel%: 17.5%</li>
              <li>Avg Distance on Barrels: 7.5%</li>
              <li>Hard Hit%: 7.5%</li>
            </ul>
          </section>
          <section>
            <h3>Fewer than 5 barrels</h3>
            <ul>
              <li>Adjusted xHR/BBE: 75%</li>
              <li>Barrel%: 17.5%</li>
              <li>Hard Hit%: 7.5%</li>
            </ul>
          </section>
        </div>

        <p>Adjusted xHR/BBE is the anchor because it is the most direct measure of stadium-neutral home-run-quality contact. If a hitter's batted balls are not producing expected home runs in a neutral context, the other components should not be able to fully rescue the score.</p>
      </section>

      <section class="about-section">
        <h2>Why Sweet Spot% Was Removed</h2>
        <p>Earlier versions of LBI included Sweet Spot%, which measures batted balls launched between 8° and 32°. That made sense in theory, but in practice it gave too much credit for launch angle without considering velocity.</p>
        <p>A weak line drive and a crushed fly ball can both fall into the sweet-spot range. For a stat focused on home-run quality, that created the wrong incentives.</p>
        <p>LBI v1.2 removes Sweet Spot% from the formula. It may still appear as a reference stat, but it is no longer part of LBI.</p>
      </section>

      <section class="about-section">
        <h2>How Scoring Works</h2>
        <p>LBI is percentile-based and scaled like a plus stat. The median qualified hitter is centered around 100. A 90th percentile component score maps around 150 in v1.2, giving elite power hitters room to separate from the field.</p>
        <p>Scores are not capped. A monster longball profile can push well above 150.</p>
      </section>

      <section class="about-section">
        <h2>Where the Data Comes From</h2>
        <p>LBI is built on Baseball Savant's public Statcast data, accessed via the pybaseball library. The Adjusted xHR/BBE component uses Savant's Home Run Tracker, which evaluates every batted ball against all 30 MLB park dimensions and applies Savant's park-factor model for temperature, altitude, and environmental conditions. Data refreshes daily after the previous day's games.</p>
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
        </div>
      </section>

      <section class="about-section">
        <h2>Feature Glossary</h2>
        <dl class="glossary">
          <div>
            <dt>Jacked Up</dt>
            <dd>The farthest home runs in the current Statcast sample.</dd>
          </div>
          <div>
            <dt>LBI Leaders</dt>
            <dd>The hitters producing the best stadium-neutral home-run-quality contact.</dd>
          </div>
          <div>
            <dt>Cheapies / Wall-Scraper Watch</dt>
            <dd>Batted balls that would clear only a small number of MLB parks.</dd>
          </div>
          <div>
            <dt>HR-capable BBE</dt>
            <dd>A batted ball classified by Savant as having home-run potential in at least one MLB park.</dd>
          </div>
          <div>
            <dt>The Hot Dog Stand</dt>
            <dd>A pitcher-accountability section built around loud, home-run-quality contact allowed.</dd>
          </div>
          <div>
            <dt>Hot Dog Index</dt>
            <dd>A plus-style score for pitchers serving up HR-capable contact, no-doubters, and high-impact home runs.</dd>
          </div>
        </dl>
      </section>

      <section class="about-section about-section--credit">
        <h2>Credits / Data Source</h2>
        <p>Data is derived from public Statcast and Baseball Savant data. The Long Ball is an independent project and is not affiliated with Major League Baseball or Baseball Savant.</p>
        <a class="back-link" href="#home">Back to leaderboard</a>
      </section>
    </article>
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
  return `
    <section class="message error">
      <h2>Leaderboard unavailable</h2>
      <p>${escapeHtml(state.error)}</p>
      <p>Run the Python data script and confirm that <code>${DATA_URL}</code> contains player rows.</p>
    </section>
  `;
}

function renderLeaderboardContent(rows) {
  return `
    ${state.status === 'loading' ? '<section class="message"><h2>Loading leaderboard...</h2></section>' : ''}
    ${state.status === 'error' ? renderError() : ''}
    ${state.status === 'ready' && rows.length > 0 ? renderTable(rows) : ''}
    ${state.status === 'ready' && rows.length === 0 ? renderEmptyState() : ''}
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
  }
}

function updateHotDogSection() {
  const hotDogSlot = document.querySelector('#hot-dog-slot');

  if (hotDogSlot) {
    hotDogSlot.innerHTML = renderHotDogSection(state.hotDogPitchers);
  }
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

function renderHomePage() {
  const rows = getVisibleRows();

  return `
    <section class="hero">
      <div class="hero-main">
        <p class="brand-pill">THELONGBALL.APP</p>
        <h1>LONGBALL</h1>
        <p class="hero-title-suffix">index.</p>
        <p class="tagline">Digging the data behind the distance</p>
        <a class="about-link" href="#about">About / Methodology</a>
      </div>
      <aside class="hero-meta">
        <strong>LBI v1.2</strong>
        <span>Pure home-run quality</span>
        <span>Stadium-neutral</span>
        <span class="hero-meta-divider" aria-hidden="true"></span>
        <span>100 = league average</span>
      </aside>
    </section>

    <div id="feature-slot">
      ${state.status === 'ready' ? renderFeatureCards(state.rows) : ''}
    </div>
    <div id="hot-dog-slot">
      ${renderHotDogSection(state.hotDogPitchers)}
    </div>
    ${state.status === 'ready' ? renderControls() : ''}

    <section class="leaderboard" aria-live="polite">
      <div class="section-heading">
        <p class="eyebrow">Core Feature</p>
        <h2>MLB Longball Index leaderboard</h2>
      </div>
      <div id="leaderboard-content">
        ${renderLeaderboardContent(rows)}
      </div>
    </section>

    ${renderFutureFeatures()}
  `;
}

function render() {
  app.innerHTML = state.view === 'about' ? renderAboutPage() : renderHomePage();

  if (state.view === 'home') {
    bindControlEvents();
    bindSortEvents();
  }
}

window.addEventListener('hashchange', () => {
  state.view = window.location.hash === '#about' ? 'about' : 'home';
  render();
});

render();
loadLeaderboard();
loadHotDogData();
