#!/usr/bin/env node

// IOWN Data Drop — GitHub Actions auto-fetcher
// Pulls all 75 tickers from Finnhub, crypto from CoinGecko, sentiment from alternative.me
// Outputs latest-drop.txt in the repo root (served via GitHub Pages)

const fs = require('fs');
const https = require('https');

const FINNHUB_KEY = process.env.FINNHUB_KEY;
if (!FINNHUB_KEY) { console.error('ERROR: FINNHUB_KEY not set'); process.exit(1); }

// ═══════════════════════════════════════════
// HOLDINGS CONFIGURATION
// ═══════════════════════════════════════════

const DIVIDEND = ['ABT','A','ADI','ATO','ADP','BKH','CAT','CHD','CL','FAST','GD','GPC','LRCX','LMT','MATX','NEE','ORI','PCAR','QCOM','DGX','SSNC','STLD','SYK','TEL','VLO'];
const GROWTH = ['AMD','AEM','ATAT','CVX','CWAN','CNX','COIN','EIX','FINV','FTNT','GFI','SUPV','HRMY','HUT','KEYS','MARA','NVDA','NXPI','OKE','PDD','HOOD','SYF','TSM','TOL'];
const DIGITAL_ETFS = ['IBIT','ETHA'];
const BENCHMARKS = ['DVY','IWS','IUSG'];
const INDEX_PROXIES = ['SPY','DIA','QQQ','IWM'];
const SECTOR_ETFS = ['XLE','XLK','XLF','XLV','XLI','XLB','XLU','XLRE','XLC','XLP','XLY'];
const COMMODITY_PROXIES = ['GLD','SLV','USO','UNG','BNO'];
const RATE_PROXIES = ['TLT'];
const VIX_TICKER = ['UVXY'];

const ALL_TICKERS = [...INDEX_PROXIES, ...VIX_TICKER, ...RATE_PROXIES, ...SECTOR_ETFS, ...COMMODITY_PROXIES, ...DIVIDEND, ...GROWTH, ...DIGITAL_ETFS, ...BENCHMARKS];

const SECTOR_NAMES = { XLE:'Energy', XLK:'Tech', XLF:'Financials', XLV:'Healthcare', XLI:'Industrials', XLB:'Materials', XLU:'Utilities', XLRE:'Real Estate', XLC:'Comm Svcs', XLP:'Staples', XLY:'Discret.' };
const INDEX_NAMES = { SPY:'S&P 500', DIA:'Dow', QQQ:'Nasdaq', IWM:'Russell 2K' };
const COMMODITY_NAMES = { GLD:'Gold', SLV:'Silver', USO:'WTI Oil', UNG:'Nat Gas', BNO:'Brent Oil' };

// ═══════════════════════════════════════════
// HTTP HELPERS
// ═══════════════════════════════════════════

function httpGet(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch(e) { reject(new Error(`JSON parse error from ${url}: ${e.message}`)); }
      });
    }).on('error', reject);
  });
}

function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

// ═══════════════════════════════════════════
// FINNHUB QUOTE FETCHER
// ═══════════════════════════════════════════

async function finnhubQuote(symbol) {
  const url = `https://finnhub.io/api/v1/quote?symbol=${encodeURIComponent(symbol)}&token=${FINNHUB_KEY}`;
  try {
    const data = await httpGet(url);
    if (data && data.c > 0) {
      return {
        symbol, price: data.c, change: data.d, changesPercentage: data.dp,
        dayHigh: data.h, dayLow: data.l, open: data.o, previousClose: data.pc
      };
    }
    return null;
  } catch(e) {
    console.warn(`  FAIL: ${symbol} - ${e.message}`);
    return null;
  }
}

async function fetchAllQuotes() {
  const results = {};
  const ok = [], fail = [];

  for (let i = 0; i < ALL_TICKERS.length; i++) {
    const sym = ALL_TICKERS[i];
    process.stdout.write(`  [${i+1}/${ALL_TICKERS.length}] ${sym}...`);

    const q = await finnhubQuote(sym);
    if (q) { results[sym] = q; ok.push(sym); process.stdout.write(` $${q.price} (${q.changesPercentage >= 0 ? '+' : ''}${q.changesPercentage}%)\n`); }
    else { fail.push(sym); process.stdout.write(' MISS\n'); }

    // Pace: ~55 calls/min
    if (i < ALL_TICKERS.length - 1) await delay(1100);
  }

  console.log(`\n  Results: ${ok.length}/${ALL_TICKERS.length} tickers`);
  if (fail.length) console.log(`  Missing: ${fail.join(', ')}`);
  return { results, ok, fail };
}

// ═══════════════════════════════════════════
// FORMAT HELPERS
// ═══════════════════════════════════════════

function fmt(n, d = 2) { if (n == null || isNaN(n)) return '—'; return Number(n).toFixed(d); }
function pct(n) { if (n == null || isNaN(n)) return '—'; return (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%'; }
function price(n) {
  if (n == null || isNaN(n)) return '—';
  if (n >= 1000) return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return '$' + fmt(n);
}

// ═══════════════════════════════════════════
// BUILD OUTPUT TEXT
// ═══════════════════════════════════════════

function buildOutput(Q, crypto, cryptoGlobal, fearGreed, news) {
  const now = new Date();
  const ds = now.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/Chicago' });
  const ts = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Chicago' });

  let o = `=== IOWN DATA DROP | ${ds} | ${ts} CT ===\n\n`;

  // INDICES
  o += '── INDICES ──\n';
  INDEX_PROXIES.forEach(s => { const q = Q[s]; if (q) o += `${INDEX_NAMES[s]}: ${price(q.price)} (${pct(q.changesPercentage)}) | O:${price(q.open)} H:${price(q.dayHigh)} L:${price(q.dayLow)} PC:${price(q.previousClose)}\n`; });
  const vix = Q['UVXY']; if (vix) o += `UVXY (VIX proxy): ${price(vix.price)} (${pct(vix.changesPercentage)})\n`;
  o += '\n── RATES ──\n';
  const tlt = Q['TLT']; if (tlt) o += `TLT (20Y Bond): ${price(tlt.price)} (${pct(tlt.changesPercentage)}) PC:${price(tlt.previousClose)}\n`;

  // SECTORS
  o += '\n── SECTORS ──\n';
  SECTOR_ETFS.map(s => ({ s, q: Q[s] })).filter(x => x.q)
    .sort((a, b) => (b.q.changesPercentage || 0) - (a.q.changesPercentage || 0))
    .forEach(({ s, q }) => { o += `${SECTOR_NAMES[s]} (${s}): ${pct(q.changesPercentage)} | ${price(q.price)}\n`; });

  // COMMODITIES
  o += '\n── COMMODITIES ──\n';
  COMMODITY_PROXIES.forEach(s => { const q = Q[s]; if (q) o += `${COMMODITY_NAMES[s]} (${s}): ${price(q.price)} (${pct(q.changesPercentage)})\n`; });

  // CRYPTO
  o += '\n── CRYPTO ──\n';
  const btc = crypto.bitcoin, eth = crypto.ethereum;
  if (btc) o += `BTC: ${price(btc.current_price)} | 24h: ${pct(btc.price_change_percentage_24h)} | 7d: ${pct(btc.price_change_percentage_7d_in_currency)} | MCap: $${fmt(btc.market_cap / 1e9, 1)}B\n`;
  if (eth) o += `ETH: ${price(eth.current_price)} | 24h: ${pct(eth.price_change_percentage_24h)} | 7d: ${pct(eth.price_change_percentage_7d_in_currency)} | MCap: $${fmt(eth.market_cap / 1e9, 1)}B\n`;
  if (cryptoGlobal.market_cap_percentage) {
    o += `BTC Dom: ${fmt(cryptoGlobal.market_cap_percentage.btc, 1)}% | Total MCap: $${fmt(cryptoGlobal.total_market_cap?.usd / 1e12, 2)}T\n`;
  }
  DIGITAL_ETFS.forEach(s => { const q = Q[s]; if (q) o += `${s}: ${price(q.price)} (${pct(q.changesPercentage)})\n`; });

  // SENTIMENT
  o += '\n── SENTIMENT ──\n';
  if (fearGreed) o += `Fear & Greed: ${fearGreed.value} (${fearGreed.value_classification})\n`;

  // DIVIDEND
  o += '\n── DIVIDEND STRATEGY (25) ──\n';
  DIVIDEND.forEach(s => { const q = Q[s]; o += q ? `${s}: ${price(q.price)} (${pct(q.changesPercentage)}) O:${price(q.open)} H:${price(q.dayHigh)} L:${price(q.dayLow)} PC:${price(q.previousClose)}\n` : `${s}: — (no data)\n`; });

  // GROWTH
  o += '\n── GROWTH HYBRID (24) ──\n';
  GROWTH.forEach(s => { const q = Q[s]; o += q ? `${s}: ${price(q.price)} (${pct(q.changesPercentage)}) O:${price(q.open)} H:${price(q.dayHigh)} L:${price(q.dayLow)} PC:${price(q.previousClose)}\n` : `${s}: — (no data)\n`; });

  // DIGITAL ETFs
  o += '\n── DIGITAL ASSET ETFs ──\n';
  DIGITAL_ETFS.forEach(s => { const q = Q[s]; o += q ? `${s}: ${price(q.price)} (${pct(q.changesPercentage)}) PC:${price(q.previousClose)}\n` : `${s}: —\n`; });

  // BENCHMARKS
  o += '\n── BENCHMARKS ──\n';
  BENCHMARKS.forEach(s => { const q = Q[s]; o += q ? `${s}: ${price(q.price)} (${pct(q.changesPercentage)}) PC:${price(q.previousClose)}\n` : `${s}: —\n`; });

  // TOP/BOTTOM MOVERS
  const allH = [...DIVIDEND, ...GROWTH, ...DIGITAL_ETFS];
  const hq = allH.map(s => ({ s, q: Q[s] })).filter(x => x.q)
    .sort((a, b) => (b.q.changesPercentage || 0) - (a.q.changesPercentage || 0));

  o += '\n── TOP 5 IOWN MOVERS ──\n';
  hq.slice(0, 5).forEach(({ s, q }) => { o += `${s}: ${pct(q.changesPercentage)} (${price(q.price)})\n`; });
  o += '\n── BOTTOM 5 IOWN MOVERS ──\n';
  hq.slice(-5).reverse().forEach(({ s, q }) => { o += `${s}: ${pct(q.changesPercentage)} (${price(q.price)})\n`; });

  // NEWS
  if (news && news.length) {
    o += '\n── HEADLINES ──\n';
    news.forEach(n => { o += `• ${n.headline} (${n.source})\n`; });
  }

  o += '\n=== END DATA DROP ===\n';
  return o;
}

// ═══════════════════════════════════════════
// MAIN
// ═══════════════════════════════════════════

async function main() {
  console.log('=== IOWN Data Drop Auto-Fetcher ===\n');
  const t0 = Date.now();

  // 1) Equity quotes
  console.log('[1/5] Fetching equity quotes via Finnhub...');
  const { results: Q, ok, fail } = await fetchAllQuotes();

  // 2) Crypto
  console.log('[2/5] Fetching crypto (CoinGecko)...');
  let crypto = {};
  try {
    const c = await httpGet('https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=bitcoin,ethereum&order=market_cap_desc&per_page=2&page=1&sparkline=false&price_change_percentage=24h,7d');
    c.forEach(x => crypto[x.id] = x);
    console.log(`  BTC: $${crypto.bitcoin?.current_price} | ETH: $${crypto.ethereum?.current_price}`);
  } catch(e) { console.warn('  Crypto fetch failed:', e.message); }

  // 3) Crypto global
  console.log('[3/5] Fetching crypto global...');
  let cryptoGlobal = {};
  try {
    const g = await httpGet('https://api.coingecko.com/api/v3/global');
    cryptoGlobal = g.data || {};
    console.log(`  BTC Dom: ${cryptoGlobal.market_cap_percentage?.btc?.toFixed(1)}%`);
  } catch(e) { console.warn('  Global fetch failed:', e.message); }

  // 4) Fear & Greed
  console.log('[4/5] Fetching Fear & Greed...');
  let fearGreed = null;
  try {
    const f = await httpGet('https://api.alternative.me/fng/?limit=1');
    fearGreed = f.data ? f.data[0] : null;
    if (fearGreed) console.log(`  Fear & Greed: ${fearGreed.value} (${fearGreed.value_classification})`);
  } catch(e) { console.warn('  F&G fetch failed:', e.message); }

  // 5) News
  console.log('[5/5] Fetching headlines...');
  let news = [];
  try {
    const n = await httpGet(`https://finnhub.io/api/v1/news?category=general&token=${FINNHUB_KEY}`);
    news = (n || []).slice(0, 8);
    console.log(`  ${news.length} headlines`);
  } catch(e) { console.warn('  News fetch failed:', e.message); }

  // Build output
  console.log('\nBuilding output...');
  const output = buildOutput(Q, crypto, cryptoGlobal, fearGreed, news);

  // Write file
  fs.writeFileSync('latest-drop.txt', output, 'utf8');
  const elapsed = ((Date.now() - t0) / 1000).toFixed(0);
  console.log(`\nDone! ${ok.length}/${ALL_TICKERS.length} tickers | ${elapsed}s`);
  console.log('Written to latest-drop.txt');
}

main().catch(err => { console.error('FATAL:', err); process.exit(1); });
