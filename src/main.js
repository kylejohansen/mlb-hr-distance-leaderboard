import './styles.css';

const DATA_URL = '/data/hr-distance-latest.json';

const columns = [
  { key: 'rank', label: 'Rank', shortLabel: '#', numeric: true },
  { key: 'player', label: 'Player' },
  { key: 'team', label: 'Team' },
  { key: 'longballIndex', label: 'LBI', numeric: true },
  { key: 'bbe', label: 'BBE', numeric: true },
  { key: 'hr', label: 'HR', numeric: true },
  { key: 'xhrPerBbe', label: 'xHR/BBE', numeric: true, unit: 'percent' },
  { key: 'barrelRate', label: 'Barrel%', shortLabel: 'Brl%', numeric: true, unit: 'percent' },
  { key: 'hardHitRate', label: 'Hard Hit%', shortLabel: 'HH%', numeric: true, unit: 'percent' },
  { key: 'avgDistanceOnBarrels', label: 'Avg Barrel Dist.', shortLabel: 'Avg Brl Dist', numeric: true, unit: 'ft' },
  { key: 'sweetSpotRate', label: 'Sweet Spot% (ref)', numeric: true, unit: 'percent' },
  { key: 'sampleBadge', label: 'Context Badge' }
];

const state = {
  rows: [],
  generatedAt: '',
  query: '',
  minHr: 1,
  sortKey: 'longballIndex',
  sortDirection: 'desc',
  status: 'loading',
  error: ''
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
              <td><span class="badge small">${escapeHtml(row.sampleBadge)}</span></td>
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
        <span>Meatball Tracker / Meatball Hall of Fame</span>
        <span>CSS launch-angle visualizer</span>
      </div>
    </section>
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

function bindEvents() {
  document.querySelector('#search-input')?.addEventListener('input', (event) => {
    state.query = event.target.value;
    render();
  });

  document.querySelector('#min-hr-select')?.addEventListener('change', (event) => {
    state.minHr = Number(event.target.value);
    render();
  });

  document.querySelectorAll('[data-sort-key]').forEach((button) => {
    button.addEventListener('click', () => {
      const nextKey = button.dataset.sortKey;

      if (state.sortKey === nextKey) {
        state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
      } else {
        state.sortKey = nextKey;
        state.sortDirection = columns.find((column) => column.key === nextKey)?.numeric ? 'desc' : 'asc';
      }

      render();
    });
  });
}

function render() {
  const rows = getVisibleRows();

  app.innerHTML = `
    <section class="hero">
      <div class="hero-main">
        <p class="brand-pill">THELONGBALL.APP</p>
        <h1>LONGBALL</h1>
        <p class="hero-title-suffix">index.</p>
        <p class="tagline">Digging the data behind the distance</p>
      </div>
      <aside class="hero-meta">
        <strong>LBI v1.2</strong>
        <span>Pure home-run quality</span>
        <span>Stadium-neutral</span>
        <span class="hero-meta-divider" aria-hidden="true"></span>
        <span>100 = league average</span>
      </aside>
    </section>

    ${state.status === 'ready' ? renderFeatureCards(state.rows) : ''}
    ${state.status === 'ready' ? renderControls() : ''}

    <section class="leaderboard" aria-live="polite">
      <div class="section-heading">
        <p class="eyebrow">Core Feature</p>
        <h2>MLB Longball Index leaderboard</h2>
      </div>
      ${state.status === 'loading' ? '<section class="message"><h2>Loading leaderboard...</h2></section>' : ''}
      ${state.status === 'error' ? renderError() : ''}
      ${state.status === 'ready' && rows.length > 0 ? renderTable(rows) : ''}
      ${state.status === 'ready' && rows.length === 0 ? renderEmptyState() : ''}
    </section>

    ${renderFutureFeatures()}
  `;

  bindEvents();
}

render();
loadLeaderboard();
