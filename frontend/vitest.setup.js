import '@testing-library/jest-dom/vitest';

// сброс URL перед каждым тестом
beforeEach(() => {
  window.location.hash = '/';
  window.history.replaceState(null, '', '/');
});
