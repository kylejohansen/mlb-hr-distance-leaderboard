import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const SITE_URL = 'https://thelongball.app';
const STATIC_DIR = 'public/static';

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replaceAll(/`([^`]+)`/g, '<code>$1</code>')
    .replaceAll(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replaceAll(/\*([^*]+)\*/g, '<em>$1</em>')
    .replaceAll(/_([^_]+)_/g, '<em>$1</em>');
}

function markdownTableToHtml(table) {
  const lines = table.split('\n').filter(Boolean);
  const headers = lines[0].split('|').slice(1, -1).map((cell) => cell.trim());
  const rows = lines.slice(2).map((line) => line.split('|').slice(1, -1).map((cell) => cell.trim()));

  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>${headers.map((header) => `<th>${inlineMarkdown(header)}</th>`).join('')}</tr>
        </thead>
        <tbody>
          ${rows.map((row) => `<tr>${row.map((cell, index) => `<td${index === 0 ? ' class="player"' : ''}>${inlineMarkdown(cell)}</td>`).join('')}</tr>`).join('')}
        </tbody>
      </table>
    </div>
`;
}

function markdownToHtml(markdown, options = {}) {
  const blocks = markdown.split(/\n{2,}/);
  const html = [];

  for (const block of blocks) {
    const trimmed = block.trim();
    if (!trimmed) continue;

    if (trimmed.startsWith('### ')) {
      html.push(`<h3>${inlineMarkdown(trimmed.slice(4))}</h3>`);
    } else if (trimmed.startsWith('## ')) {
      html.push(`<h2>${inlineMarkdown(trimmed.slice(3))}</h2>`);
    } else if (trimmed.startsWith('# ')) {
      html.push(`<h1>${inlineMarkdown(trimmed.slice(2))}</h1>`);
    } else if (options.renderTables && trimmed.startsWith('|') && trimmed.split('\n')[1]?.includes('---')) {
      html.push(markdownTableToHtml(trimmed));
    } else if (trimmed.split('\n').every((line) => line.startsWith('- '))) {
      const items = trimmed
        .split('\n')
        .map((line) => `<li>${inlineMarkdown(line.slice(2))}</li>`)
        .join('');
      html.push(`<ul>${items}</ul>`);
    } else {
      html.push(`<p>${inlineMarkdown(trimmed.replaceAll('\n', ' '))}</p>`);
    }
  }

  return html.join('\n');
}

function plainText(markdown) {
  return markdown
    .replaceAll(/`([^`]+)`/g, '$1')
    .replaceAll(/\*\*([^*]+)\*\*/g, '$1')
    .replaceAll(/\*([^*]+)\*/g, '$1')
    .replaceAll(/^#{1,6}\s+/gm, '')
    .replaceAll(/^- /gm, '')
    .replaceAll(/\s+/g, ' ')
    .trim();
}

function parseMarkdownDocument(markdown) {
  if (!markdown.startsWith('---\n')) {
    return { metadata: {}, body: markdown };
  }

  const end = markdown.indexOf('\n---', 4);
  if (end === -1) {
    return { metadata: {}, body: markdown };
  }

  const frontmatter = markdown.slice(4, end).trim();
  const body = markdown.slice(end + 4).trim();
  const metadata = {};

  for (const line of frontmatter.split('\n')) {
    const separator = line.indexOf(':');
    if (separator === -1) continue;
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim().replace(/^['"]|['"]$/g, '');
    if (key) metadata[key] = value;
  }

  return { metadata, body };
}

function pageShell({ title, fullTitle, description, canonicalPath, body, structuredData }) {
  const jsonLd = structuredData
    ? `<script type="application/ld+json">${JSON.stringify(structuredData)}</script>`
    : '';
  const documentTitle = fullTitle || `${title} | The Long Ball`;

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="description" content="${escapeHtml(description)}" />
    <link rel="canonical" href="${SITE_URL}${canonicalPath}" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="The Long Ball" />
    <meta property="og:title" content="${escapeHtml(documentTitle)}" />
    <meta property="og:description" content="${escapeHtml(description)}" />
    <meta property="og:url" content="${SITE_URL}${canonicalPath}" />
    <meta name="twitter:card" content="summary" />
    <meta name="twitter:title" content="${escapeHtml(documentTitle)}" />
    <meta name="twitter:description" content="${escapeHtml(description)}" />
    <title>${escapeHtml(documentTitle)}</title>
    ${jsonLd}
    <style>
      :root { color-scheme: light; --cream: #faf4e6; --ink: #1a1a1a; --red: #b03524; --muted: #6f6a5f; }
      body { margin: 0; background: var(--cream); color: var(--ink); font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
      main { width: min(900px, calc(100% - 32px)); margin: 48px auto; }
      nav { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 36px; font-size: 0.78rem; font-weight: 900; letter-spacing: 0.12em; text-transform: uppercase; }
      a { color: var(--red); text-decoration-thickness: 1px; text-underline-offset: 3px; }
      h1 { font-size: clamp(2.3rem, 7vw, 5rem); line-height: 0.9; margin: 0 0 24px; text-transform: uppercase; letter-spacing: 0; }
      h2 { margin-top: 36px; font-size: 1.5rem; text-transform: uppercase; }
      h3 { margin-top: 28px; }
      p, li { font-size: 1rem; line-height: 1.65; }
      .lede { color: var(--muted); font-family: Georgia, serif; font-style: italic; font-size: 1.25rem; }
      .meta { color: var(--muted); font-size: 0.85rem; }
      article, section { border-top: 1px solid rgba(176, 53, 36, 0.22); padding-top: 24px; margin-top: 24px; }
      code { background: rgba(26, 26, 26, 0.08); padding: 0.1rem 0.25rem; }
      .table-wrap { overflow-x: auto; margin-top: 18px; border-top: 2px solid var(--ink); }
      table { width: 100%; border-collapse: collapse; min-width: 720px; font-size: 0.92rem; }
      th { text-align: left; color: var(--muted); font-size: 0.72rem; letter-spacing: 0.1em; text-transform: uppercase; }
      th, td { padding: 0.7rem 0.55rem; border-bottom: 1px solid rgba(26, 26, 26, 0.14); white-space: nowrap; }
      td.numeric, th.numeric { text-align: right; }
      td.player { font-weight: 900; }
      .feature-box { border: 2px solid var(--ink); padding: 24px; background: rgba(255,255,255,0.18); }
      .feature-box h2 { margin-top: 0; }
    </style>
  </head>
  <body>
    <main>
      <nav aria-label="Primary">
        <a href="/">Longball Index</a>
        <a href="/hot-dog-stand">Hot Dog Stand</a>
        <a href="/reports/latest-longball-scouting-report">Scouting Report</a>
        <a href="/notes">Notes</a>
        <a href="/about">About</a>
      </nav>
      ${body}
    </main>
  </body>
</html>
`;
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, 'utf8'));
}

async function writeStaticPage(outputPath, options) {
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, pageShell(options));
}

function number(value, digits = 1) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '—';
  return parsed.toFixed(digits);
}

function integer(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '—';
  return String(Math.round(parsed));
}

function percent(value, digits = 1) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '—';
  return `${(parsed * 100).toFixed(digits)}%`;
}

function formatUpdatedAt(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'UTC',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short'
  }).format(date);
}

function renderTable(headers, rows) {
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>${headers.map((header) => `<th${header.numeric ? ' class="numeric"' : ''}>${escapeHtml(header.label)}</th>`).join('')}</tr>
        </thead>
        <tbody>
          ${rows.join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderHitterCells(values) {
  return values.map((value, index) => {
    const className = index === 1 ? ' class="player"' : index > 2 ? ' class="numeric"' : '';
    return `<td${className}>${value}</td>`;
  }).join('');
}

function isPublicPlayUrl(url) {
  const value = String(url || '');
  return value && !value.includes('research.mlb.com') && !value.includes('/login');
}

async function listFiles(directory, predicate) {
  try {
    const entries = await readdir(directory, { withFileTypes: true });
    return entries
      .filter((entry) => entry.isFile() && predicate(entry.name))
      .map((entry) => path.join(directory, entry.name));
  } catch {
    return [];
  }
}

function dailyEventMarkup(event, title) {
  if (!event) return `<section><h2>${escapeHtml(title)}</h2><p>No ${escapeHtml(title)} available yet.</p></section>`;
  const parks = Number.isFinite(Number(event.parksCleared)) ? `${integer(event.parksCleared)}/30 parks` : 'parks unavailable';
  const lines = [
    '<section class="feature-box">',
    `  <h2>${escapeHtml(title)}</h2>`,
    `  <p><strong>${escapeHtml(event.batter || 'Unknown batter')}</strong> vs. ${escapeHtml(event.pitcher || 'Unknown pitcher')}</p>`,
    `  <p>${escapeHtml(event.batterTeam || '—')} batting · ${escapeHtml(event.pitcherTeam || '—')} pitching</p>`,
    `  <p>${integer(event.distance)} ft · ${number(event.exitVelocity)} mph · ${escapeHtml(event.hrCat || 'Unclassified')} · ${parks}</p>`,
    `  <p class="meta">Outcome: ${escapeHtml(event.eventOutcome || '—')} · Game date: ${escapeHtml(event.gameDate || '')}</p>`
  ];
  if (isPublicPlayUrl(event.playUrl)) {
    lines.push(`  <p><a href="${escapeHtml(event.playUrl)}">Watch / View play</a></p>`);
  }
  lines.push('</section>');
  return lines.join('\n');
}

async function buildAboutPage() {
  const body = `
    <h1>About The Long Ball</h1>
    <p class="lede">The Longball Index measures the quality of a hitter's contact, specifically tuned to home run production.</p>
    <section id="longball-index">
      <h2>Longball Index</h2>
      <p>LBI is a per-contact measure. It evaluates the quality of a hitter's batted balls and does not factor in how often they make contact.</p>
      <p><a href="/docs/longball-index-methodology.md">Read the Longball Index methodology</a></p>
    </section>
    <section id="hot-dog-index">
      <h2>Hot Dog Index</h2>
      <p>The Hot Dog Index is the pitcher-facing companion to LBI. LBI asks who creates longball contact. Hot Dog Index asks who serves it up.</p>
      <p><a href="/docs/hot-dog-index-methodology.md">Read the Hot Dog Index methodology</a></p>
    </section>
    <section id="daily-features">
      <h2>Daily Features</h2>
      <p>Daily Dong, Hot Dog Robbery, and Cheapest Dong are selected from the latest available game date using Statcast and Baseball Savant Home Run Tracker event context.</p>
    </section>
    <section>
      <h2>Data Dictionary</h2>
      <p><a href="/docs/data-dictionary.md">View the field-level data dictionary</a></p>
    </section>
  `;

  await writeStaticPage(`${STATIC_DIR}/about.html`, {
    title: 'About',
    description: 'About The Long Ball, Longball Index, Hot Dog Index, and daily longball features.',
    canonicalPath: '/about',
    body,
    structuredData: {
      '@context': 'https://schema.org',
      '@type': 'WebPage',
      name: 'About The Long Ball',
      url: `${SITE_URL}/about`
    }
  });
}

async function buildNotesPages() {
  const payload = await readJson('public/data/posts.json');
  const posts = Array.isArray(payload.posts) ? payload.posts : [];
  const listItems = posts
    .map((post) => `<li><a href="/static/notes/${escapeHtml(post.slug)}.html">${escapeHtml(post.title)}</a> <span class="meta">${escapeHtml(post.date)}</span></li>`)
    .join('');

  await writeStaticPage(`${STATIC_DIR}/notes.html`, {
    title: 'Longball Notes',
    description: 'Editorial notes and weekly commentary for The Long Ball.',
    canonicalPath: '/notes',
    body: `<h1>Longball Notes</h1><p class="lede">What the board is telling us.</p><section><ul>${listItems}</ul></section>`,
    structuredData: {
      '@context': 'https://schema.org',
      '@type': 'Blog',
      name: 'Longball Notes',
      url: `${SITE_URL}/notes`
    }
  });

  await Promise.all(posts.map((post) => writeStaticPage(`${STATIC_DIR}/notes/${post.slug}.html`, {
    title: post.title,
    description: post.description,
    canonicalPath: `/notes/${post.slug}`,
    body: `
      <article>
        <p class="meta">${escapeHtml(post.date)}</p>
        ${post.html}
      </article>
    `,
    structuredData: post.structuredData
  })));
}

async function buildDocPages() {
  const docs = [
    ['data-dictionary', 'Data Dictionary'],
    ['longball-index-methodology', 'Longball Index Methodology'],
    ['hot-dog-index-methodology', 'Hot Dog Index Methodology']
  ];

  await Promise.all(docs.map(async ([slug, title]) => {
    const markdown = await readFile(`public/docs/${slug}.md`, 'utf8');
    await writeStaticPage(`${STATIC_DIR}/docs/${slug}.html`, {
      title,
      description: plainText(markdown).slice(0, 160),
      canonicalPath: `/docs/${slug}.md`,
      body: markdownToHtml(markdown, { renderTables: true }),
      structuredData: {
        '@context': 'https://schema.org',
        '@type': 'TechArticle',
        headline: title,
        url: `${SITE_URL}/docs/${slug}.md`,
        publisher: {
          '@type': 'Organization',
          name: 'The Long Ball'
        }
      }
    });
  }));
}

async function buildSeoLandingPages() {
  const longballPayload = await readJson('public/data/hr-distance-latest.json');
  const players = Array.isArray(longballPayload.players) ? longballPayload.players : [];
  const dailyFeatures = longballPayload.dailyFeatures || {};
  const updatedAt = formatUpdatedAt(longballPayload.generatedAt);
  const updatedLine = updatedAt
    ? `<p class="meta">Updated ${escapeHtml(updatedAt)}</p>`
    : '';
  const distanceRows = players
    .filter((player) => Number(player.hr) >= 5 && Number.isFinite(Number(player.avgDistance)))
    .sort((a, b) => Number(b.avgDistance) - Number(a.avgDistance) || Number(b.longestHr) - Number(a.longestHr))
    .slice(0, 50)
    .map((player, index) => `<tr>${renderHitterCells([
      integer(index + 1),
      escapeHtml(player.player),
      escapeHtml(player.team),
      integer(player.hr),
      `${number(player.avgDistance)} ft`,
      `${integer(player.longestHr)} ft`,
      `${number(player.avgExitVelocity)} mph`,
      number(player.longballIndex)
    ])}</tr>`);
  const lbiRows = [...players]
    .sort((a, b) => Number(b.longballIndex) - Number(a.longballIndex))
    .slice(0, 50)
    .map((player, index) => `<tr>${renderHitterCells([
      integer(index + 1),
      escapeHtml(player.player),
      escapeHtml(player.team),
      number(player.longballIndex),
      integer(player.bbe),
      integer(player.hr),
      percent(player.xhrPerBbe),
      percent(player.barrelRate),
      `${number(player.avgDistanceOnBarrels)} ft`,
      percent(player.hardHitRate)
    ])}</tr>`);
  const cheapieRows = players
    .filter((player) => Number(player.hr) >= 5 && Number(player.actualDoubterHr) > 0)
    .sort((a, b) => Number(b.cheapieRate) - Number(a.cheapieRate) || Number(b.actualDoubterHr) - Number(a.actualDoubterHr))
    .slice(0, 50)
    .map((player, index) => `<tr>${renderHitterCells([
      integer(index + 1),
      escapeHtml(player.player),
      escapeHtml(player.team),
      percent(player.cheapieRate),
      integer(player.actualDoubterHr),
      integer(player.hr),
      `${number(player.avgDistance)} ft`,
      number(player.longballIndex)
    ])}</tr>`);
  const dailyDong = dailyFeatures.dailyDong || longballPayload.dailyDong || null;
  const hotDogRobbery = dailyFeatures.hotDogRobbery || null;
  const cheapestDong = dailyFeatures.cheapestDong || null;
  const pages = [
    {
      slug: 'home-run-distance-leaderboard',
      title: 'MLB Home Run Distance Leaderboard',
      fullTitle: 'MLB Home Run Distance Leaderboard | The Long Ball',
      description: 'Rank MLB hitters by average home run distance, longest home run, Longball Index, and Statcast power indicators.',
      lede: 'Ranked by average actual home-run distance among hitters with 5+ HR.',
      body: renderTable(
        [
          { label: 'Rank' },
          { label: 'Player' },
          { label: 'Team' },
          { label: 'HR', numeric: true },
          { label: 'Avg HR Distance', numeric: true },
          { label: 'Longest HR', numeric: true },
          { label: 'Avg Exit Velocity', numeric: true },
          { label: 'LBI', numeric: true }
        ],
        distanceRows
      )
    },
    {
      slug: 'longball-index',
      title: 'Longball Index Leaderboard',
      fullTitle: 'Longball Index Leaderboard | Park-Neutral Home Run Quality',
      description: 'Park-neutral home run quality for MLB hitters, scaled so 100 is league average.',
      lede: '100 = league average.',
      body: renderTable(
        [
          { label: 'Rank' },
          { label: 'Player' },
          { label: 'Team' },
          { label: 'LBI', numeric: true },
          { label: 'BBE', numeric: true },
          { label: 'HR', numeric: true },
          { label: 'xHR/BBE', numeric: true },
          { label: 'Barrel%', numeric: true },
          { label: 'Avg Barrel Distance', numeric: true },
          { label: 'Hard Hit%', numeric: true }
        ],
        lbiRows
      )
    },
    {
      slug: 'cheapies',
      title: 'MLB Cheapies Leaderboard',
      fullTitle: 'MLB Cheapies Leaderboard | Home Runs That Barely Got Out',
      description: 'Home runs that barely got out, using actual Doubter HR classifications when available.',
      lede: 'Cheapies are actual home runs classified as Doubters — balls that would clear only 1-7 MLB parks.',
      body: renderTable(
        [
          { label: 'Rank' },
          { label: 'Player' },
          { label: 'Team' },
          { label: 'Cheapie Rate', numeric: true },
          { label: 'Cheapies', numeric: true },
          { label: 'HR', numeric: true },
          { label: 'Avg HR Distance', numeric: true },
          { label: 'LBI', numeric: true }
        ],
        cheapieRows
      )
    },
    {
      slug: 'daily-dong',
      title: 'Daily Dong',
      fullTitle: 'Daily Dong | Today’s Loudest MLB Home Run',
      description: 'Today\'s loudest MLB home run, plus Hot Dog Robbery and Cheapest Dong in the Tale of the Tape.',
      lede: 'Today\'s loudest longball.',
      body: [
        dailyEventMarkup(dailyDong, 'Daily Dong'),
        dailyEventMarkup(hotDogRobbery, 'Hot Dog Robbery'),
        dailyEventMarkup(cheapestDong, 'Cheapest Dong')
      ].join('')
    }
  ];

  await Promise.all(pages.map((page) => writeStaticPage(`${STATIC_DIR}/seo/${page.slug}.html`, {
    title: page.title,
    fullTitle: page.fullTitle,
    description: page.description,
    canonicalPath: `/${page.slug}`,
    body: `
      <h1>${escapeHtml(page.title)}</h1>
      <p class="lede">${escapeHtml(page.lede)}</p>
      ${updatedLine}
      <section>${page.body}</section>
    `,
    structuredData: {
      '@context': 'https://schema.org',
      '@type': 'WebPage',
      name: page.title,
      description: page.description,
      url: `${SITE_URL}/${page.slug}`
    }
  })));
}

async function buildTaleOfTheTapePages() {
  const archivePaths = await listFiles('public/data/tale-of-the-tape', (name) => name.endsWith('.json'));
  await Promise.all(archivePaths.map(async (archivePath) => {
    const payload = await readJson(archivePath);
    const gameDate = payload.gameDate || path.basename(archivePath, '.json');
    const dailyDong = payload.dailyDong || null;
    const hotDogRobbery = payload.hotDogRobbery || null;
    const cheapestDong = payload.cheapestDong || null;
    const description = `Tale of the Tape for ${gameDate}: Daily Dong, Hot Dog Robbery, and Cheapest Dong from The Long Ball.`;

    await writeStaticPage(`${STATIC_DIR}/tale-of-the-tape/${gameDate}.html`, {
      title: `Tale of the Tape ${gameDate}`,
      fullTitle: `Tale of the Tape ${gameDate} | The Long Ball`,
      description,
      canonicalPath: `/tale-of-the-tape/${gameDate}`,
      body: `
        <h1>Tale of the Tape</h1>
        <p class="lede">${escapeHtml(gameDate)} longball ledger.</p>
        <p class="meta">Archived daily feature selections from The Long Ball.</p>
        ${dailyEventMarkup(dailyDong, 'Daily Dong')}
        ${dailyEventMarkup(hotDogRobbery, 'Hot Dog Robbery')}
        ${dailyEventMarkup(cheapestDong, 'Cheapest Dong')}
      `,
      structuredData: {
        '@context': 'https://schema.org',
        '@type': 'WebPage',
        name: `Tale of the Tape ${gameDate}`,
        description,
        url: `${SITE_URL}/tale-of-the-tape/${gameDate}`,
        datePublished: gameDate,
        publisher: {
          '@type': 'Organization',
          name: 'The Long Ball'
        }
      }
    });
  }));
}

async function buildReportPages() {
  const reportPaths = await listFiles('content/reports', (name) => name.endsWith('-longball-scouting-report.md'));
  const reports = [];
  await Promise.all(reportPaths.map(async (reportPath) => {
    const markdown = await readFile(reportPath, 'utf8');
    const { metadata, body } = parseMarkdownDocument(markdown);
    const slug = path.basename(reportPath, '.md');
    const title = metadata.title || 'The Longball Scouting Report';
    const description = metadata.description || plainText(body).slice(0, 160);
    const date = metadata.date || slug.slice(0, 10);
    reports.push({ slug, title, description, date });

    await writeStaticPage(`${STATIC_DIR}/reports/${slug}.html`, {
      title,
      fullTitle: `${title} | The Long Ball`,
      description,
      canonicalPath: `/reports/${slug}`,
      body: `
        <article>
          <p class="meta">${escapeHtml(date)}</p>
          ${markdownToHtml(body, { renderTables: true })}
        </article>
      `,
      structuredData: {
        '@context': 'https://schema.org',
        '@type': 'Article',
        headline: title,
        description,
        datePublished: date,
        url: `${SITE_URL}/reports/${slug}`,
        publisher: {
          '@type': 'Organization',
          name: 'The Long Ball'
        }
      }
    });
  }));

  reports.sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const latestReport = reports[0];
  const listItems = reports
    .map((report) => `<li><a href="/reports/${escapeHtml(report.slug)}">${escapeHtml(report.title)}</a> <span class="meta">${escapeHtml(report.date)}</span></li>`)
    .join('') || '<li>No reports published yet.</li>';
  const latestLink = latestReport
    ? `<p><a href="/reports/latest-longball-scouting-report">Read the latest report</a></p>`
    : '';

  await writeStaticPage(`${STATIC_DIR}/reports.html`, {
    title: 'Longball Scouting Reports',
    description: 'Weekly Longball Scouting Report archive from The Long Ball.',
    canonicalPath: '/reports',
    body: `<h1>Longball Scouting Reports</h1><p class="lede">Weekly risers, fallers, power signals, pitcher damage, and Tale of the Tape recaps.</p>${latestLink}<section><h2>Dated Archive</h2><ul>${listItems}</ul></section>`,
    structuredData: {
      '@context': 'https://schema.org',
      '@type': 'CollectionPage',
      name: 'Longball Scouting Reports',
      url: `${SITE_URL}/reports`
    }
  });

  if (latestReport) {
    const latestHtml = await readFile(`${STATIC_DIR}/reports/${latestReport.slug}.html`, 'utf8');
    await writeFile(`${STATIC_DIR}/reports/latest-longball-scouting-report.html`, latestHtml);
  }
}

await buildAboutPage();
await buildNotesPages();
await buildDocPages();
await buildSeoLandingPages();
await buildTaleOfTheTapePages();
await buildReportPages();
console.log(`Built static HTML pages -> ${STATIC_DIR}`);
