/* Единый контекст филиала для общих страниц сайта «Диалам+». */
(function () {
  'use strict';

  var KEY = 'dialam_branch';
  var CITIES = {
    volzhsk: {
      name: 'Волжск',
      short: 'ул. Зелёная, 4Б',
      address: 'г. Волжск, ул. Зелёная, 4Б',
      phone: '+7 (958) 843-20-66',
      tel: '+79588432066',
      href: 'index.html'
    },
    orel: {
      name: 'Орёл',
      short: 'ул. Ломоносова, 6А',
      address: 'г. Орёл, ул. Ломоносова, д. 6А',
      phone: '+7 (4862) 44-31-53',
      tel: '+74862443153',
      href: 'orel.html'
    },
    nizhnevartovsk: {
      name: 'Нижневартовск',
      short: 'ул. Интернациональная, 34 А/П',
      address: 'г. Нижневартовск, ул. Интернациональная, д. 34 А/П, строение 2',
      phone: '+7 (3466) 21-90-84',
      tel: '+73466219084',
      href: 'nizhnevartovsk.html'
    },
    'yoshkar-ola': {
      name: 'Йошкар-Ола',
      short: 'ул. Анникова, 4А',
      address: 'г. Йошкар-Ола, ул. Анникова, д. 4А',
      phone: '+7 (8362) 46-49-00',
      tel: '+78362464900',
      href: 'yoshkar-ola.html'
    }
  };

  var page = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
  var branchByPage = {
    'orel.html': 'orel',
    'nizhnevartovsk.html': 'nizhnevartovsk',
    'yoshkar-ola.html': 'yoshkar-ola',
    'strahovye-kompanii-orel.html': 'orel',
    'strahovye-kompanii-nizhnevartovsk.html': 'nizhnevartovsk',
    'strahovye-kompanii-yoshkar-ola.html': 'yoshkar-ola',
    'strahovye-kompanii.html': 'volzhsk',
    'index.html': 'volzhsk',
    '': 'volzhsk'
  };
  var branch = branchByPage[page] || null;
  var stored = null;
  try { stored = localStorage.getItem(KEY); } catch (e) { /* file:// */ }

  var param = null;
  try {
    param = new URLSearchParams(location.search).get('city');
  } catch (e) { /* old browser */ }

  var city;
  if (branch) {
    // Страница филиала/главная сама задаёт контекст.
    city = branch;
    try { localStorage.setItem(KEY, city); } catch (e) {}
  } else if (param && CITIES[param]) {
    city = param;
    try { localStorage.setItem(KEY, city); } catch (e) {}
  } else if (stored && CITIES[stored]) {
    city = stored;
  } else {
    city = 'volzhsk';
  }

  if (city === 'volzhsk' && !branch) {
    return; // волжские общие страницы уже свёрстаны под Волжск
  }

  var data = CITIES[city];
  if (!data) { return; }

  function text(el, value) {
    if (el) { el.textContent = value; }
  }

  var cityText = document.querySelector('.city-select__text');
  text(cityText, data.name + ' · ' + data.short);

  var headerPhone = document.querySelector('.header-phone');
  if (headerPhone) {
    headerPhone.setAttribute('href', 'tel:' + data.tel);
    text(headerPhone, data.phone);
  }

  var mobileCity = document.querySelector('.mobile-city-info span');
  text(mobileCity, data.name + ' · ' + data.short);

  var footerPhone = document.querySelector('.footer-phone');
  if (footerPhone) {
    footerPhone.setAttribute('href', 'tel:' + data.tel);
    var footerPhoneText = footerPhone.querySelector('span');
    if (footerPhoneText) { text(footerPhoneText, data.phone); }
  }

  var footerAddress = document.querySelector('.footer-address span');
  text(footerAddress, data.address);

  var menu = document.getElementById('city-menu');
  if (menu) {
    menu.innerHTML = Object.keys(CITIES).map(function (key) {
      var c = CITIES[key];
      var info = '<span class="city-menu__info">' +
        '<span class="city-menu__name">' + c.name + '</span>' +
        '<span class="city-menu__addr">' + c.short + '</span>' +
        '</span>';
      if (key === city) {
        return '<li class="city-menu__item"><button type="button" ' +
          'class="city-menu__option is-current" aria-current="page">' +
          info + '<svg class="icon icon--check" width="24" height="24" ' +
          'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
          'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
          '<path d="M20 6 9 17l-5-5"></path></svg></button></li>';
      }
      return '<li class="city-menu__item"><a href="' + c.href + '" ' +
        'class="city-menu__option">' + info + '</a></li>';
    }).join('');
  }
})();
