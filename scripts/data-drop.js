#!/usr/bin/env node

// IOWN Data Drop v2 — GitHub Actions auto-fetcher
// Pulls: 75 tickers (quotes + candles), earnings calendar, economic calendar,
// company news for 51 holdings, crypto, sentiment, WTD/MTD/YTD/52wk data
// Outputs latest-drop.txt

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

const ALL_HOLDINGS = [...DIVIDEND, ...GROWTH, ...DIGITAL_ETFS];
const ALL_TICKERS = [...INDEX_PROXIES, ...VIX_TICKER, ...RATE_PROXIES, ...SECTOR_ETFS, ...COMMODITY_PROXIES, ...DIVIDEND, ...GROWTH, ...DIGITAL_ETFS, ...BENCHMARKS];

const SECTOR_NAMES = { XLE:'Energy', XLK:'Tech', XLF:'Financials', XLV:'Healthcare', XLI:'Industrials', XLB:'Materials', XLU:'Utilities', XLRE:'Real Estate', XLC:'Comm Svcs', XLP:'Staples', XLY:'Discret.' };
const INDEX_NAMES = { SPY:'S&P 500', DIA:'Dow', QQQ:'Nasdaq', IWM:'Russell 2K' };
const COMMODITY_NAMES = { GLD:'Gold', SLV:'Silver', USO:'WTI Oil', UNG:'Nat Gas', BNO:'Brent Oil' };

// ═══════════════════════════════════════════
// HTTP + TIMING HELPERS
// ═══════════════════════════════════════════

function httpGet(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch(e) { reject(new Error(`JSON parse error: ${e.message}`)); }
      });
    }).on('error', reject);
  });
}

function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

function fhUrl(endpoint) {
  return `https://finnhub.io/api/v1/${endpoint}&token=${FINNHUB_KEY}`;
}

function fhUrlQ(endpoint) {
  return `https://finnhub.io/api/v1/${endpoint}?token=${FINNHUB_KEY}`;
}

// Date helpers
function toUnix(date) { return Math.floor(date.getTime() / 1000); }

function getMonday(d) {
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  return new Date(d.getFullYear(), d.getMonth(), diff);
}

function dateStr(d) {
  return d.toISOString().slice(0, 10);
}

// ═══════════════════════════════════════════
// FINNHUB FETCHERS
// ═══════════════════════════════════════════

async function finnhubQuote(symbol) {
  try {
    const data = await httpGet(`https://finnhub.io/api/v1/quote?symbol=${encodeURIComponent(symbol)}&token=${FINNHUB_KEY}`);
    if (data && data.c > 0) {
      return { symbol, price: data.c, change: data.d, changesPercentage: data.dp, dayHigh: data.h, dayLow: data.l, open: data.o, previousClose: data.pc };
    }
    return null;
  } catch(e) { return null; }
}

async function finnhubCandles(symbol, fromDate, toDate) {
  try {
    const from = toUnix(fromDate);
    const to = toUnix(toDate);
    const data = await httpGet(`https://finnhub.io/api/v1/stock/candle?symbol=${encodeURIComponent(symbol)}&resolution=D&from=${from}&to=${to}&token=${FINNHUB_KEY}`);
    if (data && data.s === 'ok' && data.c && data.c.length > 0) {
      return { closes: data.c, highs: data.h, lows: data.l, opens: data.o, timestamps: data.t, volumes: data.v };
    }
    return null;
  } catch(e) { return null; }
}

async function finnhubEarnings(fromDate, toDate) {
  try {
    const data = await httpGet(fhUrl(`calendar/earnings?from=${fromDate}&to=${toDate}`));
    return (data && data.earningsCalendar) ? data.earningsCalendar : [];
  } catch(e) { return []; }
}

async function finnhubEconomicCalendar(fromDate, toDate) {
  try {
    const data = await httpGet(fhUrl(`calendar/economic?from=${fromDate}&to=${toDate}`));
    return (data && data.economicCalendar) ? data.economicCalendar : [];
  } catch(e) { return []; }
}

async function finnhubCompanyNews(symbol, fromDate, toDate) {
  try {
    const data = await httpGet(fhUrl(`company-news?symbol=${encodeURIComponent(symbol)}&from=${fromDate}&to=${toDate}`));
    return Array.isArray(data) ? data.slice(0, 3) : [];
  } catch(e) { return []; }
}

// ═══════════════════════════════════════════
// SEQUENTIAL FETCHER WITH PACING
// ═══════════════════════════════════════════

async function fetchAllQuotes() {
  const results = {};
  const ok = [], fail = [];
  for (let i = 0; i < ALL_TICKERS.length; i++) {
    const sym = ALL_TICKERS[i];
    process.stdout.write(`  [${i+1}/${ALL_TICKERS.length}] ${sym}...`);
    const q = await finnhubQuote(sym);
    if (q) { results[sym] = q; ok.push(sym); process.stdout.write(` $${q.price} (${q.changesPercentage >= 0 ? '+' : ''}${q.changesPercentage}%)\n`); }
    else { fail.push(sym); process.stdout.write(' MISS\n'); }
    if (i < ALL_TICKERS.length - 1) await delay(1100);
  }
  return { results, ok, fail };
}

async function fetchAllCandles(tickers, fromDate, toDate) {
  const results = {};
  for (let i = 0; i < tickers.length; i++) {
    const sym = tickers[i];
    process.stdout.write(`  [${i+1}/${tickers.length}] ${sym} candles...`);
    const c = await finnhubCandles(sym, fromDate, toDate);
    if (c) { results[sym] = c; process.stdout.write(` ${c.closes.length} days\n`); }
    else { process.stdout.write(' MISS\n'); }
    if (i < tickers.length - 1) await delay(1100);
  }
  return results;
}

async function fetchHoldingNews(holdings, fromDate, toDate) {
  const results = {};
  for (let i = 0; i < holdings.length; i++) {
    const sym = holdings[i];
    process.stdout.write(`  [${i+1}/${holdings.length}] ${sym} news...`);
    const news = await finnhubCompanyNews(sym, fromDate, toDate);
    if (news.length) { results[sym] = news; process.stdout.write(` ${news.length} articles\n`); }
    else { process.stdout.write(' none\n'); }
    if (i < holdings.length - 1) await delay(1100);
  }
  return results;
}

// ═══════════════════════════════════════════
// CANDLE ANALYSIS — WTD, MTD, YTD, 52wk, ATH
// ═══════════════════════════════════════════

function analyzeCandles(candles, currentPrice) {
  if (!candles || !candles.closes || candles.closes.length < 2) return null;

  const now = new Date();
  const yearStart = new Date(now.getFullYear(), 0, 1);
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const weekStart = getMonday(now);

  const yearStartUnix = toUnix(yearStart);
  const monthStartUnix = toUnix(monthStart);
  const weekStartUnix = toUnix(weekStart);

  // 52-week high/low from all candle data
  const high52w = Math.max(...candles.highs);
  const low52w = Math.min(...candles.lows);

  // YTD data
  let ytdHigh = null, ytdLow = null, ytdStartClose = null;
  let mtdStartClose = null, wtdStartClose = null;

  for (let i = 0; i < candles.timestamps.length; i++) {
    const t = candles.timestamps[i];
    const h = candles.highs[i];
    const l = candles.lows[i];
    const c = candles.closes[i];

    // YTD
    if (t >= yearStartUnix) {
      if (ytdStartClose === null) ytdStartClose = candles.closes[Math.max(0, i - 1)] || c;
      ytdHigh = ytdHigh === null ? h : Math.max(ytdHigh, h);
      ytdLow = ytdLow === null ? l : Math.min(ytdLow, l);
    }

    // MTD
    if (t >= monthStartUnix && mtdStartClose === null) {
      mtdStartClose = candles.closes[Math.max(0, i - 1)] || c;
    }

    // WTD
    if (t >= weekStartUnix && wtdStartClose === null) {
      wtdStartClose = candles.closes[Math.max(0, i - 1)] || c;
    }
  }

  // Calculate returns
  const ytdReturn = ytdStartClose ? ((currentPrice - ytdStartClose) / ytdStartClose) * 100 : null;
  const mtdReturn = mtdStartClose ? ((currentPrice - mtdStartClose) / mtdStartClose) * 100 : null;
  const wtdReturn = wtdStartClose ? ((currentPrice - wtdStartClose) / wtdStartClose) * 100 : null;
  const pctFrom52wHigh = high52w ? ((currentPrice - high52w) / high52w) * 100 : null;
  const pctFrom52wLow = low52w ? ((currentPrice - low52w) / low52w) * 100 : null;

  // Simple moving averages from closing prices
  const closes = candles.closes;
  const len = closes.length;
  const sma50 = len >= 50 ? closes.slice(len - 50).reduce((a, b) => a + b, 0) / 50 : null;
  const sma100 = len >= 100 ? closes.slice(len - 100).reduce((a, b) => a + b, 0) / 100 : null;
  const sma200 = len >= 200 ? closes.slice(len - 200).reduce((a, b) => a + b, 0) / 200 : null;

  return {
    high52w, low52w, ytdHigh, ytdLow,
    ytdReturn, mtdReturn, wtdReturn,
    pctFrom52wHigh, pctFrom52wLow,
    sma50, sma100, sma200
  };
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
// BUILD OUTPUT
// ═══════════════════════════════════════════

function buildOutput(Q, CA, crypto, cryptoGlobal, fearGreed, news, earningsYesterday, earningsToday, econToday, holdingNews) {
  const now = new Date();
  const ds = now.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/Chicago' });
  const ts = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Chicago' });

  let o = `=== IOWN DATA DROP v2 | ${ds} | ${ts} CT ===\n\n`;

  // ── ECONOMIC CALENDAR ──
  if (econToday.length) {
    o += '── ECONOMIC CALENDAR (TODAY) ──\n';
    econToday.slice(0, 15).forEach(e => {
      const time = e.time || '';
      const event = e.event || '';
      const actual = e.actual != null ? `Actual: ${e.actual}` : '';
      const estimate = e.estimate != null ? `Est: ${e.estimate}` : '';
      const prior = e.prev != null ? `Prior: ${e.prev}` : '';
      const parts = [actual, estimate, prior].filter(Boolean).join(' | ');
      o += `${time} ${event}${parts ? ' [' + parts + ']' : ''}\n`;
    });
    o += '\n';
  }

  // ── EARNINGS CALENDAR ──
  if (earningsYesterday.length || earningsToday.length) {
    if (earningsYesterday.length) {
      o += '── EARNINGS (YESTERDAY) ──\n';
      // Flag IOWN holdings
      const iownYesterday = earningsYesterday.filter(e => ALL_HOLDINGS.includes(e.symbol));
      const otherYesterday = earningsYesterday.filter(e => !ALL_HOLDINGS.includes(e.symbol));
      if (iownYesterday.length) {
        o += '⚡ IOWN: ' + iownYesterday.map(e => {
          const beat = e.epsActual != null && e.epsEstimate != null ? (e.epsActual > e.epsEstimate ? 'BEAT' : e.epsActual < e.epsEstimate ? 'MISS' : 'INLINE') : '';
          return `${e.symbol} EPS:${e.epsActual || '—'} vs ${e.epsEstimate || '—'} ${beat}`;
        }).join(' | ') + '\n';
      }
      o += otherYesterday.slice(0, 15).map(e => `${e.symbol} EPS:${e.epsActual || '—'} vs Est:${e.epsEstimate || '—'}`).join(' | ') + '\n\n';
    }
    if (earningsToday.length) {
      o += '── EARNINGS (TODAY) ──\n';
      const iownToday = earningsToday.filter(e => ALL_HOLDINGS.includes(e.symbol));
      if (iownToday.length) o += '⚡ IOWN REPORTING: ' + iownToday.map(e => `${e.symbol} Est:${e.epsEstimate || '—'}`).join(' | ') + '\n';
      o += earningsToday.slice(0, 20).map(e => `${e.symbol} Est:${e.epsEstimate || '—'}`).join(' | ') + '\n\n';
    }
  }

  // ── INDICES ──
  o += '── INDICES ──\n';
  INDEX_PROXIES.forEach(s => {
    const q = Q[s], c = CA[s];
    if (q) {
      let line = `${INDEX_NAMES[s]}: ${price(q.price)} (${pct(q.changesPercentage)}) | O:${price(q.open)} H:${price(q.dayHigh)} L:${price(q.dayLow)} PC:${price(q.previousClose)}`;
      if (c) {
        const p = q.price;
        let ma = '';
        if (c.sma50) ma += ` 50d:${price(c.sma50)}${p > c.sma50 ? '▲' : '▼'}`;
        if (c.sma200) ma += ` 200d:${price(c.sma200)}${p > c.sma200 ? '▲' : '▼'}`;
        line += ma;
      }
      o += line + '\n';
    }
  });
  const vix = Q['UVXY']; if (vix) o += `UVXY (VIX proxy): ${price(vix.price)} (${pct(vix.changesPercentage)})\n`;
  o += '\n';

  // ── RATES ──
  o += '── RATES ──\n';
  const tlt = Q['TLT']; if (tlt) o += `TLT (20Y Bond): ${price(tlt.price)} (${pct(tlt.changesPercentage)}) PC:${price(tlt.previousClose)}\n`;
  o += '\n';

  // ── SECTORS ──
  o += '── SECTORS ──\n';
  SECTOR_ETFS.map(s => ({ s, q: Q[s], c: CA[s] })).filter(x => x.q)
    .sort((a, b) => (b.q.changesPercentage || 0) - (a.q.changesPercentage || 0))
    .forEach(({ s, q, c }) => {
      let line = `${SECTOR_NAMES[s]} (${s}): ${pct(q.changesPercentage)} | ${price(q.price)}`;
      if (c) line += ` | WTD:${pct(c.wtdReturn)} MTD:${pct(c.mtdReturn)}`;
      o += line + '\n';
    });
  o += '\n';

  // ── COMMODITIES ──
  o += '── COMMODITIES ──\n';
  COMMODITY_PROXIES.forEach(s => {
    const q = Q[s], c = CA[s];
    if (q) {
      let line = `${COMMODITY_NAMES[s]} (${s}): ${price(q.price)} (${pct(q.changesPercentage)})`;
      if (c) line += ` | WTD:${pct(c.wtdReturn)} MTD:${pct(c.mtdReturn)} YTD:${pct(c.ytdReturn)}`;
      o += line + '\n';
    }
  });
  o += '\n';

  // ── CRYPTO ──
  o += '── CRYPTO ──\n';
  const btc = crypto.bitcoin, eth = crypto.ethereum;
  if (btc) o += `BTC: ${price(btc.current_price)} | 24h: ${pct(btc.price_change_percentage_24h)} | 7d: ${pct(btc.price_change_percentage_7d_in_currency)} | MCap: $${fmt(btc.market_cap / 1e9, 1)}B\n`;
  if (eth) o += `ETH: ${price(eth.current_price)} | 24h: ${pct(eth.price_change_percentage_24h)} | 7d: ${pct(eth.price_change_percentage_7d_in_currency)} | MCap: $${fmt(eth.market_cap / 1e9, 1)}B\n`;
  if (cryptoGlobal.market_cap_percentage) {
    o += `BTC Dom: ${fmt(cryptoGlobal.market_cap_percentage.btc, 1)}% | Total MCap: $${fmt(cryptoGlobal.total_market_cap?.usd / 1e12, 2)}T\n`;
  }
  DIGITAL_ETFS.forEach(s => { const q = Q[s]; if (q) o += `${s}: ${price(q.price)} (${pct(q.changesPercentage)})\n`; });
  o += '\n';

  // ── SENTIMENT ──
  o += '── SENTIMENT ──\n';
  if (fearGreed) o += `Fear & Greed: ${fearGreed.value} (${fearGreed.value_classification})\n`;
  o += '\n';

  // ── HELPER: format a holding line with candle data ──
  function holdingLine(s) {
    const q = Q[s], c = CA[s];
    if (!q) return `${s}: — (no data)\n`;
    let line = `${s}: ${price(q.price)} (${pct(q.changesPercentage)}) O:${price(q.open)} H:${price(q.dayHigh)} L:${price(q.dayLow)} PC:${price(q.previousClose)}`;
    if (c) {
      const p = q.price;
      let ma = '';
      if (c.sma50) ma += ` 50d:${price(c.sma50)}${p > c.sma50 ? '▲' : '▼'}`;
      if (c.sma200) ma += ` 200d:${price(c.sma200)}${p > c.sma200 ? '▲' : '▼'}`;
      line += ma;
    }
    return line + '\n';
  }

  // ── DIVIDEND STRATEGY ──
  o += '── DIVIDEND STRATEGY (25) ──\n';
  DIVIDEND.forEach(s => { o += holdingLine(s); });
  o += '\n';

  // ── GROWTH HYBRID ──
  o += '── GROWTH HYBRID (24) ──\n';
  GROWTH.forEach(s => { o += holdingLine(s); });
  o += '\n';

  // ── DIGITAL ASSET ETFs ──
  o += '── DIGITAL ASSET ETFs ──\n';
  DIGITAL_ETFS.forEach(s => { o += holdingLine(s); });
  o += '\n';

  // ── BENCHMARKS ──
  o += '── BENCHMARKS ──\n';
  BENCHMARKS.forEach(s => {
    const q = Q[s], c = CA[s];
    if (q) {
      let line = `${s}: ${price(q.price)} (${pct(q.changesPercentage)}) PC:${price(q.previousClose)}`;
      if (c) line += ` | WTD:${pct(c.wtdReturn)} MTD:${pct(c.mtdReturn)} YTD:${pct(c.ytdReturn)}`;
      o += line + '\n';
    }
  });
  o += '\n';

  // ── TOP & BOTTOM MOVERS ──
  const allH = [...DIVIDEND, ...GROWTH, ...DIGITAL_ETFS];
  const hq = allH.map(s => ({ s, q: Q[s] })).filter(x => x.q)
    .sort((a, b) => (b.q.changesPercentage || 0) - (a.q.changesPercentage || 0));

  o += '── TOP 5 IOWN MOVERS ──\n';
  hq.slice(0, 5).forEach(({ s, q }) => {
    const c = CA[s];
    let line = `${s}: ${pct(q.changesPercentage)} (${price(q.price)})`;
    if (c) line += ` | WTD:${pct(c.wtdReturn)} from52wH:${pct(c.pctFrom52wHigh)}`;
    o += line + '\n';
  });
  o += '\n── BOTTOM 5 IOWN MOVERS ──\n';
  hq.slice(-5).reverse().forEach(({ s, q }) => {
    const c = CA[s];
    let line = `${s}: ${pct(q.changesPercentage)} (${price(q.price)})`;
    if (c) line += ` | WTD:${pct(c.wtdReturn)} from52wH:${pct(c.pctFrom52wHigh)}`;
    o += line + '\n';
  });
  o += '\n';

  // ── HOLDINGS NEWS ──
  const newsSymbols = Object.keys(holdingNews).filter(s => holdingNews[s].length > 0);
  if (newsSymbols.length) {
    o += '── IOWN HOLDINGS NEWS (24h) ──\n';
    newsSymbols.forEach(s => {
      holdingNews[s].slice(0, 2).forEach(n => {
        o += `${s}: ${n.headline} (${n.source})\n`;
      });
    });
    o += '\n';
  }

  // ── GENERAL HEADLINES ──
  if (news && news.length) {
    o += '── HEADLINES ──\n';
    news.forEach(n => { o += `• ${n.headline} (${n.source})\n`; });
    o += '\n';
  }

  o += '=== END DATA DROP ===\n';
  return o;
}

// ═══════════════════════════════════════════
// MAIN
// ═══════════════════════════════════════════

async function main() {
  console.log('=== IOWN Data Drop v2 ===\n');
  const t0 = Date.now();
  const now = new Date();

  // Date ranges
  const today = dateStr(now);
  const yesterday = dateStr(new Date(now.getTime() - 86400000));
  const newsFrom = dateStr(new Date(now.getTime() - 2 * 86400000)); // 2 days back for news
  const oneYearAgo = new Date(now.getFullYear() - 1, now.getMonth(), now.getDate());

  // 1) Equity quotes
  console.log('[1/8] Fetching equity quotes via Finnhub...');
  const { results: Q, ok, fail } = await fetchAllQuotes();
  console.log(`  ${ok.length}/${ALL_TICKERS.length} tickers\n`);

  // 2) Candle data (1 year) for WTD/MTD/YTD/52wk
  console.log('[2/8] Fetching 1-year candle data...');
  const rawCandles = await fetchAllCandles(ALL_TICKERS, oneYearAgo, now);
  const CA = {};
  for (const sym of ALL_TICKERS) {
    if (rawCandles[sym] && Q[sym]) {
      CA[sym] = analyzeCandles(rawCandles[sym], Q[sym].price);
    }
  }
  console.log(`  ${Object.keys(CA).length} tickers analyzed\n`);

  // 3) Earnings calendar
  console.log('[3/8] Fetching earnings calendar...');
  const earningsYesterday = await finnhubEarnings(yesterday, yesterday);
  await delay(1100);
  const earningsToday = await finnhubEarnings(today, today);
  console.log(`  Yesterday: ${earningsYesterday.length} | Today: ${earningsToday.length}\n`);
  await delay(1100);

  // 4) Economic calendar
  console.log('[4/8] Fetching economic calendar...');
  const econRaw = await finnhubEconomicCalendar(today, today);
  // Filter to US events
  const econToday = econRaw.filter(e => e.country === 'US' || e.country === 'United States' || !e.country);
  console.log(`  ${econToday.length} US events today\n`);
  await delay(1100);

  // 5) Company news for all 51 holdings
  console.log('[5/8] Fetching holdings news (51 tickers)...');
  const holdingNews = await fetchHoldingNews(ALL_HOLDINGS, newsFrom, today);
  console.log(`  ${Object.keys(holdingNews).length} tickers with news\n`);

  // 6) Crypto
  console.log('[6/8] Fetching crypto (CoinGecko)...');
  let crypto = {};
  try {
    const c = await httpGet('https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=bitcoin,ethereum&order=market_cap_desc&per_page=2&page=1&sparkline=false&price_change_percentage=24h,7d');
    c.forEach(x => crypto[x.id] = x);
    console.log(`  BTC: $${crypto.bitcoin?.current_price} | ETH: $${crypto.ethereum?.current_price}`);
  } catch(e) { console.warn('  Crypto failed:', e.message); }

  // 7) Crypto global
  console.log('[7/8] Fetching crypto global...');
  let cryptoGlobal = {};
  try {
    const g = await httpGet('https://api.coingecko.com/api/v3/global');
    cryptoGlobal = g.data || {};
  } catch(e) { console.warn('  Global failed:', e.message); }

  // 8) Fear & Greed + General News
  console.log('[8/8] Fetching sentiment & headlines...');
  let fearGreed = null;
  try {
    const f = await httpGet('https://api.alternative.me/fng/?limit=1');
    fearGreed = f.data ? f.data[0] : null;
    if (fearGreed) console.log(`  Fear & Greed: ${fearGreed.value} (${fearGreed.value_classification})`);
  } catch(e) { console.warn('  F&G failed:', e.message); }

  let news = [];
  try {
    const n = await httpGet(`https://finnhub.io/api/v1/news?category=general&token=${FINNHUB_KEY}`);
    news = (n || []).slice(0, 8);
    console.log(`  ${news.length} headlines`);
  } catch(e) { console.warn('  News failed:', e.message); }

  // Build output
  console.log('\nBuilding output...');
  const output = buildOutput(Q, CA, crypto, cryptoGlobal, fearGreed, news, earningsYesterday, earningsToday, econToday, holdingNews);

  fs.writeFileSync('latest-drop.txt', output, 'utf8');
  const elapsed = ((Date.now() - t0) / 1000).toFixed(0);
  console.log(`\nDone! ${ok.length}/${ALL_TICKERS.length} tickers | ${Object.keys(CA).length} candles | ${elapsed}s`);
  console.log('Written to latest-drop.txt');
}

main().catch(err => { console.error('FATAL:', err); process.exit(1); });
