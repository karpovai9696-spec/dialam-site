/* js/search.js — клиентский поиск по сайту «Диалам+» (без внешних запросов) */
(function () {
  'use strict';

  var PAGES = [
    { url: 'index.html', title: 'Диалам+ — центр амбулаторного гемодиализа в Волжске', description: 'Главная страница центра амбулаторного гемодиализа «Диалам+» в Волжске.', keywords: 'главная, диализ, нефрология, ОМС, Волжск, гемодиализ' },
    { url: 'orel.html', title: 'Филиал «Орёл» — Диалам+', description: 'Центр амбулаторного гемодиализа в Орле: адрес, телефон, режим работы, услуги и вакансии.', keywords: 'Орёл, Орел, Ломоносова, 6А, гемодиализ, гостевой диализ, нефролог, ОМС, вакансии, +7 4862 44-31-53' },
    { url: 'nizhnevartovsk.html', title: 'Филиал «Нижневартовск» — Диалам+', description: 'Центр амбулаторного гемодиализа в Нижневартовске: адрес, телефон, режим работы и услуги по ОМС.', keywords: 'Нижневартовск, Нижневартовске, Интернациональная, 34 А/П, гемодиализ, гостевой диализ, нефролог, ОМС, +7 3466 21-90-84' },
    { url: 'oklinike.html', title: 'О клинике в Волжске — Диалам+', description: 'Сведения о центре «Диалам+»: история, условия и документы.', keywords: 'о клинике, центр, диализ, Волжск, сведения, документы' },
    { url: 'uslugi.html', title: 'Услуги — Диалам+', description: 'Услуги центра: амбулаторный и гостевой диализ, консультации, наблюдение.', keywords: 'услуги, гемодиализ, гостевой диализ, консультация, наблюдение, ОМС' },
    { url: 'novosti.html', title: 'Новости центра и полезные статьи — Диалам+', description: 'Новости центра «Диалам+» и полезные статьи о гемодиализе.', keywords: 'новости, статьи, полезное, события, диализ' },
    { url: 'kontakty.html', title: 'Контакты — Диалам+', description: 'Контакты центра «Диалам+» в Волжске: телефон, адрес, режим работы.', keywords: 'контакты, телефон, адрес, отзывы, связь, Волжск' },
    { url: 'rezhim-i-grafik-raboty.html', title: 'Режим и график работы — Диалам+', description: 'Режим работы и график смен центра амбулаторного гемодиализа.', keywords: 'режим, график, смены, работа, расписание, диализ' },
    { url: 'besplatnye-konsultacii.html', title: 'Бесплатные консультации — Диалам+', description: 'Бесплатные консультации специалистов и запись на приём по полису ОМС.', keywords: 'консультации, бесплатно, запись, ОМС, приём, нефролог' },
    { url: 'strahovye-kompanii.html', title: 'Страховые компании — Диалам+', description: 'Страховые медицинские организации, работающие с центром по ОМС.', keywords: 'страховые, ОМС, полис, СОГАЗ, КАПИТАЛ, страховая' },
    { url: 'programma-gos-garantii.html', title: 'Программы гос. гарантий — Диалам+', description: 'Программа государственных гарантий бесплатного оказания медицинской помощи.', keywords: 'программа, госгарантии, ОМС, помощь, бесплатно, документы' },
    { url: 'licenzii.html', title: 'Лицензии — Диалам+', description: 'Лицензии и разрешительные документы центра «Диалам+».', keywords: 'лицензии, лицензия, документы, проверка, разрешительная, медицинская' },
    { url: 'rukovodstvo.html', title: 'Руководство — Диалам+', description: 'Руководство центра «Диалам+»: главный врач и администрация.', keywords: 'руководство, главный врач, директор, администрация, клиника' },
    { url: 'svedeniya-o-medrabotnikah.html', title: 'Сведения о медицинских работниках — Диалам+', description: 'Сведения о медицинских работниках центра: образование и сертификаты.', keywords: 'медработники, врачи, персонал, образование, сертификаты' },
    { url: 'dostizheniya-i-nagrady.html', title: 'Достижения и награды — Диалам+', description: 'Достижения и награды центра «Диалам+».', keywords: 'достижения, награды, дипломы, благодарность, конкурс' },
    { url: 'nadzornye-organy.html', title: 'Надзорные органы — Диалам+', description: 'Контакты надзорных органов в сфере охраны здоровья.', keywords: 'надзорные, минздрав, росздравнадзор, роспотребнадзор, жалобы, контроль' },
    { url: 'vakansii.html', title: 'Вакансии — Диалам+', description: 'Актуальные вакансии центра «Диалам+» и контакты для резюме.', keywords: 'вакансии, работа, резюме, нефролог, инженер, трудоустройство' },
    { url: 'prava-grazhdan.html', title: 'Права граждан — Диалам+', description: 'Права и обязанности граждан в сфере охраны здоровья, защита прав пациентов.', keywords: 'права, обязанности, пациенты, закон, 323-ФЗ, защита' },
    { url: 'pravila-zapisi.html', title: 'Правила записи на консультацию и диализ — Диалам+', description: 'Способы записи, необходимые документы и порядок приёма.', keywords: 'запись, правила, консультация, диализ, документы, приём' },
    { url: 'medikamentoznoe-obespechenie.html', title: 'Медикаментозное обеспечение — Диалам+', description: 'Назначение препаратов, перечень ЖНВЛП и льготное лекарственное обеспечение.', keywords: 'лекарства, препараты, ЖНВЛП, льготы, рецепты, обеспечение' },
    { url: 'vidy-i-usloviya-pomoschi.html', title: 'Виды и условия помощи по ОМС — Диалам+', description: 'Виды и условия получения специализированной медицинской помощи по полису ОМС.', keywords: 'виды помощи, ОМС, условия, полис, гемодиализ, амбулаторно' },
    { url: 'platnye-uslugi.html', title: 'Платные услуги — Диалам+', description: 'Информация о платных медицинских услугах центра «Диалам+».', keywords: 'платные услуги, прейскурант, цены, ОМС, информация' },
    { url: 'pokazateli-dostupnosti.html', title: 'Показатели доступности и качества — Диалам+', description: 'Показатели доступности и качества медицинской помощи.', keywords: 'показатели, доступность, качество, помощь, ОМС' },
    { url: 'anketa-ocenki-kachestva.html', title: 'Анкета оценки качества услуг — Диалам+', description: 'Анонимная анкета оценки качества услуг центра.', keywords: 'анкета, оценка, качество, опрос, отзыв, услуги' },
    { url: 'rezultaty-nezavisimoj-ocenki.html', title: 'Результаты независимой оценки — Диалам+', description: 'Результаты независимой оценки качества условий оказания услуг.', keywords: 'независимая оценка, качество, bus.gov.ru, результаты' },
    { url: 'usloviya-i-poryadok.html', title: 'Условия и порядок оказания помощи — Диалам+', description: 'Условия, порядок и сроки оказания медицинской помощи.', keywords: 'условия, порядок, сроки, помощь, ОМС, документы' },
    { url: 'dopolnitelnaya-informaciya.html', title: 'Дополнительная информация — Диалам+', description: 'Дополнительная информация для пациентов центра.', keywords: 'дополнительно, информация, пациенты, права, документы' },
    { url: 'pravila-vnutrennego-rasporyadka.html', title: 'Правила внутреннего распорядка — Диалам+', description: 'Правила внутреннего распорядка для пациентов.', keywords: 'правила, распорядок, пациенты, поведение, центр' },
    { url: 'nabor-socialnyh-uslug.html', title: 'Набор социальных услуг и льготы — Диалам+', description: 'Набор социальных услуг и льготы для пациентов.', keywords: 'социальные услуги, льготы, НСУ, соцзащита, лекарства' },
    { url: 'poleznoe.html', title: 'Полезное: гемодиализ и фистула — Диалам+', description: 'Полезная информация о гемодиализе, сосудистом доступе и питании.', keywords: 'гемодиализ, фистула, доступ, питание, полезное, диализ' },
    { url: 'politika-obrabotki-pdn.html', title: 'Политика обработки персональных данных — Диалам+', description: 'Политика обработки персональных данных ООО «Диалам+».', keywords: 'политика, персональные данные, ПДн, 152-ФЗ, оператор, согласие' },
    { url: 'soglasie-na-obrabotku-pdn.html', title: 'Согласие на обработку персональных данных — Диалам+', description: 'Текст согласия на обработку персональных данных при заполнении форм.', keywords: 'согласие, персональные данные, ПДн, обработка, отзыв, формы' },
    { url: 'sitemap.html', title: 'Карта сайта — Диалам+', description: 'Карта сайта: все разделы и страницы центра «Диалам+».', keywords: 'карта, sitemap, страницы, разделы, навигация, сайт' },
    { url: 'search.html', title: 'Поиск по сайту — Диалам+', description: 'Поиск по страницам, услугам и документам сайта центра «Диалам+».', keywords: 'поиск, запрос, найти, страницы, результаты' }
  ];

  function plural(n, one, few, many) {
    var m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }

  document.addEventListener('DOMContentLoaded', function () {
    var form = document.querySelector('.search-form');
    if (!form) return;

    var input = document.getElementById('site-search');
    var resultsBox = document.getElementById('search-results');
    var emptyBox = document.getElementById('search-empty');
    var countBox = document.querySelector('.search-count');
    var timer = null;

    function normalize(s) {
      return s.toLowerCase().replace(/ё/g, 'е').trim();
    }

    function search(query) {
      var words = normalize(query).split(/\s+/).filter(Boolean);
      if (!words.length) return [];
      var scored = [];
      for (var i = 0; i < PAGES.length; i++) {
        var page = PAGES[i];
        var haystack = normalize(page.title + ' ' + page.description + ' ' + page.keywords);
        var score = 0;
        for (var w = 0; w < words.length; w++) {
          if (haystack.indexOf(words[w]) !== -1) score++;
        }
        if (score > 0) scored.push({ page: page, score: score });
      }
      scored.sort(function (a, b) {
        if (b.score !== a.score) return b.score - a.score;
        return a.page.title.localeCompare(b.page.title, 'ru');
      });
      return scored;
    }

    function render(query) {
      var q = query.trim();
      resultsBox.textContent = '';
      if (!q) {
        resultsBox.hidden = true;
        emptyBox.hidden = true;
        countBox.hidden = true;
        return;
      }
      var found = search(q);
      countBox.hidden = false;
      countBox.textContent = 'Найдено ' + found.length + ' ' + plural(found.length, 'страница', 'страницы', 'страниц') + ' по запросу «' + q + '»';
      if (!found.length) { emptyBox.hidden = false; return; }
      emptyBox.hidden = true;
      for (var i = 0; i < found.length; i++) {
        var page = found[i].page;
        var link = document.createElement('a');
        link.className = 'search-result';
        link.href = page.url;
        var title = document.createElement('span');
        title.className = 'search-result__title';
        title.textContent = page.title;
        var desc = document.createElement('span');
        desc.className = 'search-result__desc';
        desc.textContent = page.description;
        link.appendChild(title);
        link.appendChild(desc);
        resultsBox.appendChild(link);
      }
    }

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      render(input.value);
    });

    input.addEventListener('input', function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () { render(input.value); }, 180);
    });

    // Поддержка перехода search.html?q=...
    var params = new URLSearchParams(window.location.search);
    var initial = params.get('q');
    if (initial) { input.value = initial; render(initial); }
  });
})();