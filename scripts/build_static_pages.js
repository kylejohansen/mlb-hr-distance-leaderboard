import { mkdir, readFile, writeFile } from 'node:fs/promises';
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
    .replaceAll(/\*([^*]+)\*/g, '<em>$1</em>');
}

function markdownToHtml(markdown) {
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
    </style>
  </head>
  <body>
    <main>
      <nav aria-label="Primary">
        <a href="/">Longball Index</a>
        <a href="/hot-dog-stand">Hot Dog Stand</a>
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
      body: markdownToHtml(markdown),
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
  const pages = [
    {
      slug: 'home-run-distance-leaderboard',
      title: 'MLB Home Run Distance Leaderboard',
      fullTitle: 'MLB Home Run Distance Leaderboard | The Long Ball',
      description: 'Rank MLB hitters by average home run distance, longest home run, Longball Index, and Statcast power indicators.',
      lede: 'A Statcast-powered leaderboard for the hitters doing the most damage in the air.',
      body: [
        'The Long Ball tracks home run distance, longest home runs, and Longball Index context in one place.',
        'Use the main leaderboard to compare average HR distance, longest HR, xHR/BBE, Barrel%, Hard Hit%, PullAir%, and reference Sweet Spot%.',
        '<a href="/">View the current Longball Index leaderboard</a>'
      ]
    },
    {
      slug: 'longball-index',
      title: 'Longball Index Leaderboard',
      fullTitle: 'Longball Index Leaderboard | Park-Neutral Home Run Quality',
      description: 'Park-neutral home run quality for MLB hitters, scaled so 100 is league average.',
      lede: 'Pure home-run quality, stadium-neutral.',
      body: [
        'Longball Index measures the quality of a hitter\'s home-run contact per batted ball event.',
        'LBI v1.2 is anchored by Baseball Savant Adjusted xHR/BBE, with Barrel%, Avg Distance on Barrels, and Hard Hit% rounding out the score.',
        '<a href="/docs/longball-index-methodology.md">Read the Longball Index methodology</a>'
      ]
    },
    {
      slug: 'cheapies',
      title: 'MLB Cheapies Leaderboard',
      fullTitle: 'MLB Cheapies Leaderboard | Home Runs That Barely Got Out',
      description: 'Home runs that barely got out, using actual Doubter HR classifications when available.',
      lede: 'Home runs that barely got out.',
      body: [
        'Cheapies are actual home runs classified as Doubters by Baseball Savant Home Run Tracker when event-level classification is available.',
        'The top-card rate is actual Doubter HR divided by actual HR total, with fallback copy used only when true classification is unavailable.',
        '<a href="/about/cheapies">Read the Cheapies definition</a>'
      ]
    },
    {
      slug: 'daily-dong',
      title: 'Daily Dong',
      fullTitle: 'Daily Dong | Today’s Loudest MLB Home Run',
      description: 'Today\'s loudest MLB home run, plus Hot Dog Robbery and Cheapest Dong in the Tale of the Tape.',
      lede: 'Today\'s loudest longball.',
      body: [
        'Tale of the Tape preserves the Daily Dong, Hot Dog Robbery, and Cheapest Dong for each available game date.',
        'Daily Dong is selected from actual home runs; Hot Dog Robbery highlights the best HR-capable ball that stayed in the yard; Cheapest Dong finds the flimsiest homer that still counted.',
        '<a href="/data/daily-features-2026.json">View the Daily Features archive JSON</a>'
      ]
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
      <section>
        ${page.body.map((paragraph) => `<p>${paragraph}</p>`).join('')}
      </section>
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

await buildAboutPage();
await buildNotesPages();
await buildDocPages();
await buildSeoLandingPages();
console.log(`Built static HTML pages -> ${STATIC_DIR}`);
