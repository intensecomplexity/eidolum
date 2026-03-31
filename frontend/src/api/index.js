// API configuration - using Railway URL directly
import axios from 'axios';

const API_BASE = 'https://eidolum-production.up.railway.app';

const api = axios.create({
  baseURL: `${API_BASE}/api`,
});

export function getLeaderboard(params = {}) {
  return api.get('/leaderboard', { params }).then(r => r.data);
}

export function getForecaster(id, params = {}) {
  return api.get(`/forecaster/${id}`, { params }).then(r => r.data);
}

export function getSectors() {
  return api.get('/sectors').then(r => r.data);
}

export function getForecasterSectors(id) {
  return api.get(`/forecaster/${id}/sectors`).then(r => r.data);
}

export function getAssetConsensus(ticker, days = 90) {
  return api.get(`/asset/${ticker}/consensus`, { params: { days } }).then(r => r.data);
}

export function getPendingPredictions() {
  return api.get('/pending-predictions').then(r => r.data);
}

export function getActivityFeed(limit = 30) {
  return api.get('/activity-feed', { params: { limit } }).then(r => r.data);
}

export function getHomepageStats() {
  return api.get('/homepage-stats').then(r => r.data);
}

export function getTrendingTickers() {
  return api.get('/trending-tickers').then(r => r.data);
}

export function getTickerDetail(ticker) {
  return api.get(`/ticker/${ticker}/detail`).then(r => r.data);
}

export function getControversial() {
  return api.get('/controversial').then(r => r.data);
}

export function getHotStreaks() {
  return api.get('/hot-streaks').then(r => r.data);
}

export function getPlatforms() {
  return api.get('/platforms').then(r => r.data);
}

export function getPlatformDetail(platformId, params = {}) {
  return api.get(`/platforms/${platformId}`, { params }).then(r => r.data);
}

export function triggerSync() {
  return api.post('/sync').then(r => r.data);
}

export function getPredictionOfTheDay() {
  return api.get('/prediction-of-the-day').then(r => r.data);
}

export function getReportCards(params = {}) {
  return api.get('/report-cards', { params }).then(r => r.data);
}

export function getRareSignals() {
  return api.get('/rare-signals').then(r => r.data);
}

export function createFollow(data) {
  return api.post('/follows', data).then(r => r.data);
}

export function removeFollow(data) {
  return api.post('/follows/unfollow', data).then(r => r.data);
}

export function getFollowerCount(forecasterId) {
  return api.get(`/follows/count/${forecasterId}`).then(r => r.data);
}

export function subscribeNewsletter(email) {
  return api.post('/newsletter/subscribe', { email }).then(r => r.data);
}

export function generateNewsletter() {
  return api.get('/newsletter/generate').then(r => r.data);
}

export function getSavedPredictions(userId) {
  return api.get('/saved-predictions', { params: { user_identifier: userId } }).then(r => r.data);
}

export function getSavedIds(userId) {
  return api.get('/saved-predictions/ids', { params: { user_identifier: userId } }).then(r => r.data);
}

export function savePrediction(userId, predictionId) {
  return api.post('/saved-predictions', { user_identifier: userId, prediction_id: predictionId }).then(r => r.data);
}

export function unsavePrediction(userId, predictionId) {
  return api.delete(`/saved-predictions/${predictionId}`, { params: { user_identifier: userId } }).then(r => r.data);
}

export function updateSavedNote(userId, predictionId, note) {
  return api.patch(`/saved-predictions/${predictionId}/note`, { user_identifier: userId, personal_note: note }).then(r => r.data);
}

export function getSaveCount(predictionId) {
  return api.get(`/saved-predictions/count/${predictionId}`).then(r => r.data);
}

export function getForecasterPositions(forecasterId) {
  return api.get(`/forecaster/${forecasterId}/positions`).then(r => r.data);
}

export function getAllForecasters(params = {}) {
  return api.get('/forecasters/all', { params }).then(r => r.data);
}

export function getConflictPredictions() {
  return api.get('/predictions/conflicts').then(r => r.data);
}

export function getTodayPredictions() {
  return api.get('/predictions/today').then(r => r.data);
}

export function getRecentPredictions(params = {}) {
  return api.get('/predictions/recent', { params }).then(r => r.data);
}

export function getContrarianSignals() {
  return api.get('/contrarian-signals').then(r => r.data);
}

export function getContrarianSignal(ticker) {
  return api.get(`/contrarian-signals/${ticker}`).then(r => r.data);
}

export function getPowerRankings(periodDays = 30) {
  return api.get('/power-rankings', { params: { period_days: periodDays } }).then(r => r.data);
}

export function getInversePortfolio(forecasterId, startingAmount = 10000) {
  return api.get(`/inverse-portfolio/${forecasterId}`, { params: { starting_amount: startingAmount } }).then(r => r.data);
}

// ——— Search ———

export function searchTickers(query) {
  return api.get('/tickers/search', { params: { q: query } }).then(r => r.data);
}

export function universalSearch(query) {
  return api.get('/search', { params: { q: query }, headers: authHeaders() }).then(r => r.data);
}

export function getFriendSuggestions() {
  return api.get('/friends/suggestions', { headers: authHeaders() }).then(r => r.data);
}

// ——— User Auth & Predictions API ———

function authHeaders() {
  const token = localStorage.getItem('eidolum_token') || '';
  return { Authorization: `Bearer ${token}` };
}

export function registerUser(username, email, password, display_name, ref) {
  const body = { username, email, password, display_name };
  if (ref) body.ref = ref;
  return api.post('/auth/register', body).then(r => r.data);
}

export function loginUser(email, password) {
  return api.post('/auth/login', { email, password }).then(r => r.data);
}

export function getMe() {
  return api.get('/auth/me', { headers: authHeaders() }).then(r => r.data);
}

export function getGoogleAuthUrl() {
  return api.get('/auth/google/login').then(r => r.data);
}

export function googleCallback(code) {
  return api.get('/auth/google/callback', { params: { code } }).then(r => r.data);
}

export function completeOnboarding() {
  return api.post('/auth/onboarding-complete', {}, { headers: authHeaders() }).then(r => r.data);
}

export function forgotPassword(email) {
  return api.post('/auth/forgot-password', { email }).then(r => r.data);
}

export function resetPassword(token, password) {
  return api.post('/auth/reset-password', { token, password }).then(r => r.data);
}

export function getNotifications(unreadOnly = false, limit = 50) {
  return api.get('/notifications', { params: { unread_only: unreadOnly, limit }, headers: authHeaders() }).then(r => r.data);
}

export function markNotificationRead(id) {
  return api.post(`/notifications/read/${id}`, {}, { headers: authHeaders() }).then(r => r.data);
}

export function markAllNotificationsRead() {
  return api.post('/notifications/read-all', {}, { headers: authHeaders() }).then(r => r.data);
}

// ——— Notification Preferences ———

export function getNotificationPrefs() {
  return api.get('/settings/notifications', { headers: authHeaders() }).then(r => r.data);
}

export function setNotificationPrefs(preferences) {
  return api.put('/settings/notifications', { preferences }, { headers: authHeaders() }).then(r => r.data);
}

// ——— Sharing ———

export function getPredictionShareData(predictionId) {
  return api.get(`/predictions/${predictionId}/share-data`).then(r => r.data);
}

export function getProfileShareData(userId) {
  return api.get(`/profiles/${userId}/share-data`).then(r => r.data);
}

// ——— Friend Requests ———

export function acceptFriendRequest(userId) {
  return api.post(`/follows/${userId}/accept`, {}, { headers: authHeaders() }).then(r => r.data);
}

export function declineFriendRequest(userId) {
  return api.post(`/follows/${userId}/decline`, {}, { headers: authHeaders() }).then(r => r.data);
}

export function getFriendRequests() {
  return api.get('/follows/requests', { headers: authHeaders() }).then(r => r.data);
}

export function getSentRequests() {
  return api.get('/follows/sent', { headers: authHeaders() }).then(r => r.data);
}

// ——— Compare ———

export function compareUsers(id1, id2) {
  return api.get(`/compare/${id1}/${id2}`).then(r => r.data);
}

// ——— Prediction Detail ———

export function getPredictionDetail(predictionId, source = 'user') {
  return api.get(`/predictions/detail/${predictionId}`, { params: { source }, headers: authHeaders() }).then(r => r.data);
}

// ——— Comments ———

export function getComments(predictionId, source, limit = 20, offset = 0) {
  return api.get(`/comments/${predictionId}/${source}`, { params: { limit, offset } }).then(r => r.data);
}

export function postComment(predictionId, source, comment) {
  return api.post('/comments', { prediction_id: predictionId, prediction_source: source, comment }, { headers: authHeaders() }).then(r => r.data);
}

export function deleteComment(commentId) {
  return api.delete(`/comments/${commentId}`, { headers: authHeaders() }).then(r => r.data);
}

export function getCommentCount(predictionId, source) {
  return api.get(`/comments/count/${predictionId}/${source}`).then(r => r.data);
}

// ——— Reactions ———

export function getReactions(predictionId, source) {
  return api.get(`/reactions/${predictionId}/${source}`, { headers: authHeaders() }).then(r => r.data);
}

export function addReaction(predictionId, source, reaction) {
  return api.post('/reactions', { prediction_id: predictionId, prediction_source: source, reaction }, { headers: authHeaders() }).then(r => r.data);
}

export function removeReaction(predictionId, source) {
  return api.delete(`/reactions/${predictionId}/${source}`, { headers: authHeaders() }).then(r => r.data);
}

// ——— Daily Challenge ———

export function getTodayChallenge() {
  return api.get('/daily-challenge/today', { headers: authHeaders() }).then(r => r.data);
}

export function enterDailyChallenge(direction) {
  return api.post('/daily-challenge/enter', { direction }, { headers: authHeaders() }).then(r => r.data);
}

export function getChallengeHistory() {
  return api.get('/daily-challenge/history', { headers: authHeaders() }).then(r => r.data);
}

export function getChallengeLeaderboard() {
  return api.get('/daily-challenge/leaderboard').then(r => r.data);
}

// ——— Nudges ———

export function getNudges() {
  return api.get('/nudges', { headers: authHeaders() }).then(r => r.data);
}

// ——— Earnings ———

export function getUpcomingEarnings() {
  return api.get('/earnings/upcoming').then(r => r.data);
}

export function getTickerEarnings(symbol) {
  return api.get(`/earnings/ticker/${symbol}`).then(r => r.data);
}

// ——— Heatmap ———

export function getSectorHeatmap() {
  return api.get('/heatmap/sectors').then(r => r.data);
}

export function getTickerHeatmap() {
  return api.get('/heatmap/tickers').then(r => r.data);
}

// ——— Accuracy History ———

export function getUserAccuracyHistory(userId) {
  return api.get(`/users/${userId}/accuracy-history`).then(r => r.data);
}

export function getUserAccuracyByCategory(userId) {
  return api.get(`/users/${userId}/accuracy-by-category`).then(r => r.data);
}

export function getAnalystAccuracyHistory(name) {
  return api.get(`/analysts/${encodeURIComponent(name)}/accuracy-history`).then(r => r.data);
}

// ——— Analysts ———

export function getAnalysts(q) {
  const params = {};
  if (q) params.q = q;
  return api.get('/analysts', { params }).then(r => r.data);
}

export function getAnalystProfile(name) {
  return api.get(`/analysts/${encodeURIComponent(name)}`).then(r => r.data);
}

export function getAnalystPredictions(name, params = {}) {
  return api.get(`/analysts/${encodeURIComponent(name)}/predictions`, { params }).then(r => r.data);
}

export function getAnalystRankings() {
  return api.get('/analysts/rankings').then(r => r.data);
}

export function getAnalystSubscriptionStatus(name) {
  const token = localStorage.getItem('eidolum_token');
  const config = token ? { headers: { Authorization: `Bearer ${token}` } } : {};
  return api.get(`/analysts/${encodeURIComponent(name)}/subscription-status`, config).then(r => r.data);
}

export function subscribeAnalyst(name, email) {
  const token = localStorage.getItem('eidolum_token');
  const config = token ? { headers: { Authorization: `Bearer ${token}` } } : {};
  return api.post(`/analysts/${encodeURIComponent(name)}/subscribe`, email ? { email } : {}, config).then(r => r.data);
}

export function unsubscribeAnalyst(name, email) {
  const token = localStorage.getItem('eidolum_token');
  const params = email ? { email } : {};
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  return api.delete(`/analysts/${encodeURIComponent(name)}/subscribe`, { headers, params }).then(r => r.data);
}

// ——— Controversial ———

export function getControversialPredictions() {
  return api.get('/predictions/controversial').then(r => r.data);
}

export function getMostDebatedTickers() {
  return api.get('/predictions/most-debated-tickers').then(r => r.data);
}

export function getBoldCalls() {
  return api.get('/predictions/bold-calls').then(r => r.data);
}

// ——— Prediction Templates ———

export function getPredictionTemplates() {
  return api.get('/prediction-templates').then(r => r.data);
}

// ——— Settings ———

export function setPriceAlerts(enabled) {
  return api.put('/settings/price-alerts', { enabled }, { headers: authHeaders() }).then(r => r.data);
}

export function setEmailPreferences(weeklyDigest) {
  return api.put('/settings/email-preferences', { weekly_digest: weeklyDigest }, { headers: authHeaders() }).then(r => r.data);
}

export function updateSocialLinks(links) {
  return api.put('/profile/social', links, { headers: authHeaders() }).then(r => r.data);
}

// ——— Watchlist ———

export function getWatchlist() {
  return api.get('/watchlist', { headers: authHeaders() }).then(r => r.data);
}

export function getWatchlistFeed() {
  return api.get('/watchlist/feed', { headers: authHeaders() }).then(r => r.data);
}

export function addToWatchlist(ticker) {
  return api.post(`/watchlist/${ticker}`, {}, { headers: authHeaders() }).then(r => r.data);
}

export function removeFromWatchlist(ticker) {
  return api.delete(`/watchlist/${ticker}`, { headers: authHeaders() }).then(r => r.data);
}

// ——— I Told You So ———

export function getToldYouSo(predictionId) {
  return api.get(`/predictions/${predictionId}/told-you-so`).then(r => r.data);
}

export function trackReferral(ref, predictionId) {
  return api.post('/referrals/track', null, { params: { ref, prediction_id: predictionId } }).then(r => r.data);
}

// ——— Global Stats ———

export function getGlobalStats() {
  return api.get('/stats/global').then(r => r.data);
}

// ——— Activity Feed ———

export function getGlobalFeed(before, ticker) {
  const params = {};
  if (before) params.before = before;
  if (ticker) params.ticker = ticker;
  return api.get('/feed/global', { params }).then(r => r.data);
}

export function getFollowingFeed(before) {
  const params = {};
  if (before) params.before = before;
  return api.get('/feed/following', { params, headers: authHeaders() }).then(r => r.data);
}

// ——— Ticker Detail ———

export function getTickerPrice(symbol) {
  return api.get(`/tickers/${symbol}/price`).then(r => r.data);
}

export function getTickerCurrentPrice(ticker) {
  return api.get(`/ticker/${ticker}/price`).then(r => r.data);
}

export function getTickerPredictions(symbol, status = 'pending') {
  return api.get(`/tickers/${symbol}/predictions`, { params: { status } }).then(r => r.data);
}

export function getTickerTopCallers(symbol) {
  return api.get(`/tickers/${symbol}/top-callers`).then(r => r.data);
}

export function getTickerStats(symbol) {
  return api.get(`/tickers/${symbol}/stats`).then(r => r.data);
}

export function submitUserPrediction(data) {
  return api.post('/user-predictions/submit', data, { headers: authHeaders() }).then(r => r.data);
}

export function deletePrediction(predictionId) {
  return api.delete(`/user-predictions/${predictionId}`, { headers: authHeaders() }).then(r => r.data);
}

export function getDeletionStatus() {
  return api.get('/user-predictions/deletion-status', { headers: authHeaders() }).then(r => r.data);
}

export function getUserPredictions(userId, outcome) {
  const params = {};
  if (outcome) params.outcome = outcome;
  return api.get(`/user-predictions/${userId}`, { params }).then(r => r.data);
}

export function getUserProfile(userId) {
  const token = localStorage.getItem('eidolum_token');
  const config = token ? { headers: { Authorization: `Bearer ${token}` } } : {};
  return api.get(`/users/${userId}/profile`, config).then(r => r.data);
}

export function getCommunityLeaderboard(userType) {
  const params = {};
  if (userType) params.user_type = userType;
  return api.get('/leaderboard/community', { params }).then(r => r.data);
}

export function getUserAchievements(userId) {
  return api.get(`/users/${userId}/achievements`).then(r => r.data);
}

// ——— Phase 2: Follows, Duels, Seasons, Consensus, Expiring ———

export function followUser(userId) {
  return api.post(`/follows/${userId}`, {}, { headers: authHeaders() }).then(r => r.data);
}

export function unfollowUser(userId) {
  return api.delete(`/follows/${userId}`, { headers: authHeaders() }).then(r => r.data);
}

export function getFollowers(userId) {
  return api.get(`/follows/${userId}/followers`).then(r => r.data);
}

export function getFollowing(userId) {
  return api.get(`/follows/${userId}/following`).then(r => r.data);
}

export function getFeed() {
  return api.get('/feed', { headers: authHeaders() }).then(r => r.data);
}

export function createDuel(data) {
  return api.post('/duels/challenge', data, { headers: authHeaders() }).then(r => r.data);
}

export function acceptDuel(duelId, target) {
  return api.post(`/duels/${duelId}/accept`, { target }, { headers: authHeaders() }).then(r => r.data);
}

export function declineDuel(duelId) {
  return api.post(`/duels/${duelId}/decline`, {}, { headers: authHeaders() }).then(r => r.data);
}

export function getMyDuels(status) {
  const params = {};
  if (status) params.status = status;
  return api.get('/duels/mine', { params, headers: authHeaders() }).then(r => r.data);
}

export function getDuelRecord(userId) {
  return api.get(`/users/${userId}/duel-record`).then(r => r.data);
}

export function getSeasons() {
  return api.get('/seasons').then(r => r.data);
}

export function getCurrentSeason() {
  return api.get('/seasons/current').then(r => r.data);
}

export function getSeasonLeaderboard(seasonId) {
  return api.get(`/seasons/${seasonId}/leaderboard`).then(r => r.data);
}

export function getTickerConsensus(ticker) {
  return api.get(`/consensus/${ticker}`).then(r => r.data);
}

export function getAllConsensus() {
  return api.get('/consensus').then(r => r.data);
}

export function getExpiringPredictions() {
  return api.get('/predictions/expiring').then(r => r.data);
}

export function getUserPerks() {
  return api.get('/xp/me', { headers: authHeaders() }).then(r => r.data);
}

export function setCustomTitle(title) {
  return api.post('/profile/title', { title }, { headers: authHeaders() }).then(r => r.data);
}

export function getTitleOptions() {
  return api.get('/profile/title-options').then(r => r.data);
}

export function getMyXp() {
  return api.get('/xp/me', { headers: authHeaders() }).then(r => r.data);
}

export function getXpHistory() {
  return api.get('/xp/history', { headers: authHeaders() }).then(r => r.data);
}

export function getMyRival() {
  return api.get('/rivals/mine', { headers: authHeaders() }).then(r => r.data);
}

export function getLivePrices(tickers) {
  return api.get('/predictions/live-prices', { params: { tickers: tickers.join(',') } }).then(r => r.data);
}

export function getWeeklyChallenge() {
  const token = localStorage.getItem('eidolum_token');
  const config = token ? { headers: { Authorization: `Bearer ${token}` } } : {};
  return api.get('/weekly-challenge/current', config).then(r => r.data);
}

// Admin API (requires Bearer token in sessionStorage)
function adminHeaders() {
  const token = sessionStorage.getItem('admin_token') || '';
  return { Authorization: `Bearer ${token}` };
}

export function getAdminPredictions(params = {}) {
  return api.get('/admin/predictions', { params, headers: adminHeaders() }).then(r => r.data);
}

export function deleteAdminPrediction(id) {
  return api.delete(`/admin/predictions/${id}`, { headers: adminHeaders() }).then(r => r.data);
}

export function bulkDeletePredictions(ids) {
  return api.delete('/admin/predictions/bulk', { data: { ids }, headers: adminHeaders() }).then(r => r.data);
}

export function createAdminPrediction(data) {
  return api.post('/admin/predictions', data, { headers: adminHeaders() }).then(r => r.data);
}

export function getSchedulerStatus() {
  return api.get('/admin/scheduler-status', { headers: adminHeaders() }).then(r => r.data);
}

export default api;
export { API_BASE };
