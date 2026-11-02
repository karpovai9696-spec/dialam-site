(function () {
  'use strict';

  /* ===== 1. ВЕРСИЯ ДЛЯ СЛАБОВИДЯЩИХ ===== */
  var A11Y_STORAGE_KEY = 'dialam_a11y_mode';
  var rootHtml = document.documentElement;
  var a11yButtons = document.querySelectorAll('.a11y-toggle');

  function getSavedA11yState() {
    try {
      return window.localStorage.getItem(A11Y_STORAGE_KEY) === '1';
    } catch (e) {
      return false;
    }
  }

  function saveA11yState(isEnabled) {
    try {
      if (isEnabled) {
        window.localStorage.setItem(A11Y_STORAGE_KEY, '1');
      } else {
        window.localStorage.removeItem(A11Y_STORAGE_KEY);
      }
    } catch (e) {
      /* Безопасный fallback для строгого режима file:// */
    }
  }

  function applyA11yMode(isEnabled) {
    rootHtml.classList.toggle('a11y-mode', isEnabled);
    for (var i = 0; i < a11yButtons.length; i++) {
      var btn = a11yButtons[i];
      btn.setAttribute('aria-pressed', isEnabled ? 'true' : 'false');
      var label = btn.querySelector('.a11y-toggle__label');
      if (label) {
        label.textContent = isEnabled ? 'Обычная версия' : 'Версия для слабовидящих';
      }
    }
  }

  applyA11yMode(getSavedA11yState());

  for (var i = 0; i < a11yButtons.length; i++) {
    a11yButtons[i].addEventListener('click', function () {
      var nextState = !rootHtml.classList.contains('a11y-mode');
      applyA11yMode(nextState);
      saveA11yState(nextState);
    });
  }

  /* ===== 2. МОБИЛЬНОЕ МЕНЮ ===== */
  var navToggle = document.querySelector('.nav-toggle');
  var mainNav = document.getElementById('main-nav');

  function setMobileMenuOpen(isOpen) {
    if (!navToggle || !mainNav) {
      return;
    }
    mainNav.classList.toggle('is-open', isOpen);
    navToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    navToggle.setAttribute(
      'aria-label',
      isOpen ? 'Закрыть меню навигации' : 'Открыть меню навигации'
    );
  }

  if (navToggle && mainNav) {
    navToggle.addEventListener('click', function () {
      var isOpen = mainNav.classList.contains('is-open');
      setMobileMenuOpen(!isOpen);
    });

    var navLinks = mainNav.querySelectorAll('a');
    for (var j = 0; j < navLinks.length; j++) {
      navLinks[j].addEventListener('click', function () {
        setMobileMenuOpen(false);
      });
    }
  }

  /* ===== 3. ПЕРЕКЛЮЧАТЕЛЬ ГОРОДА ===== */
  var citySwitcher = document.querySelector('.city-switcher');
  var citySelectBtn = document.querySelector('.city-select');
  var cityMenu = document.getElementById('city-menu');

  function setCityMenuOpen(isOpen) {
    if (!citySelectBtn || !cityMenu) {
      return;
    }
    citySelectBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    if (isOpen) {
      cityMenu.removeAttribute('hidden');
      var firstOption = cityMenu.querySelector('.city-menu__option');
      if (firstOption && typeof firstOption.focus === 'function') {
        firstOption.focus();
      }
    } else {
      cityMenu.setAttribute('hidden', '');
    }
  }

  if (citySelectBtn && cityMenu) {
    citySelectBtn.addEventListener('click', function () {
      var isExpanded = citySelectBtn.getAttribute('aria-expanded') === 'true';
      setCityMenuOpen(!isExpanded);
    });

    var currentOption = cityMenu.querySelector('.city-menu__option.is-current');
    if (currentOption) {
      currentOption.addEventListener('click', function () {
        setCityMenuOpen(false);
        citySelectBtn.focus();
      });
    }
  }

  document.addEventListener('click', function (event) {
    if (citySwitcher && cityMenu && !cityMenu.hasAttribute('hidden')) {
      if (!citySwitcher.contains(event.target)) {
        setCityMenuOpen(false);
      }
    }
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      if (cityMenu && !cityMenu.hasAttribute('hidden')) {
        setCityMenuOpen(false);
        if (citySelectBtn) {
          citySelectBtn.focus();
        }
      }
      if (mainNav && mainNav.classList.contains('is-open')) {
        setMobileMenuOpen(false);
        if (navToggle) {
          navToggle.focus();
        }
      }
    }
  });

  /* ===== 4. СТАТУС «СЕЙЧАС ОТКРЫТО» (EUROPE/MOSCOW) ===== */
  var statusEl = document.getElementById('clinic-status');

  function updateClinicStatus() {
    if (!statusEl) {
      return;
    }

    var isOpen = true;

    try {
      var formatter = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Europe/Moscow',
        weekday: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
      });

      var parts = formatter.formatToParts(new Date());
      var weekday = '';
      var hour = 0;
      var minute = 0;

      for (var k = 0; k < parts.length; k++) {
        if (parts[k].type === 'weekday') {
          weekday = parts[k].value;
        } else if (parts[k].type === 'hour') {
          hour = parseInt(parts[k].value, 10);
        } else if (parts[k].type === 'minute') {
          minute = parseInt(parts[k].value, 10);
        }
      }

      if (hour === 24) {
        hour = 0;
      }

      var totalMinutes = hour * 60 + minute;
      var weekdayIndex = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }[weekday];
      if (weekdayIndex === undefined) {
        weekdayIndex = -1;
      }
      var startHour = parseInt(statusEl.getAttribute('data-open-hour') || '7', 10);
      var endHour = parseInt(statusEl.getAttribute('data-close-hour') || '22', 10);
      var overnight = endHour <= startHour;
      var withinHours;

      if (startHour === endHour) {
        withinHours = true;
      } else if (!overnight) {
        withinHours = totalMinutes >= startHour * 60 && totalMinutes < endHour * 60;
      } else {
        withinHours = totalMinutes >= startHour * 60 || totalMinutes < endHour * 60;
      }

      if (overnight && totalMinutes < endHour * 60) {
        // 00:00–04:00 — хвост смены предыдущего дня; воскресной смены нет.
        var previousDay = (weekdayIndex + 6) % 7;
        isOpen = withinHours && previousDay !== 0;
      } else {
        isOpen = withinHours && weekdayIndex !== 0;
      }
    } catch (e) {
      isOpen = true;
    }

    statusEl.classList.toggle('is-closed', !isOpen);
    statusEl.setAttribute(
      'title',
      'Режим работы (МСК): ' +
        (statusEl.getAttribute('data-hours-label') || 'Пн–Сб 07:00–22:00, Вс — выходной')
    );

    var textNode = statusEl.querySelector('.status__text');
    if (textNode) {
      textNode.textContent = isOpen ? 'Сейчас открыто' : 'Сейчас закрыто';
    }
  }

  updateClinicStatus();
  window.setInterval(updateClinicStatus, 60000);
})();