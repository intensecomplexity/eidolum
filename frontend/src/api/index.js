// Build: 2026-03-26 api=api.eidolum.com
import axios from 'axios';

const api = axios.create({
  baseURL: `${import.meta.env.VITE_API_URL || 'https://api.eidolum.com'}/api`,
});

export function getLeaderboard(params = {}) {
  return api.get('/leaderboard', { params }).then(r => r.data);
}

export function getForecaster(id) {
  return api.get(`/forecaster/${id}`).then(r => r.data);
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

export function getConflictPredictions() {
  return api.get('/predictions/conflicts').then(r => r.data);
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

export default api;
