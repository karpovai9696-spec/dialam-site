/* Прототип: реальная отправка появится на этапе подключения бэкенда */
(function () {
  'use strict';

  var form = document.getElementById('consultation-form');
  if (!form) {
    return;
  }

  var errorBox = document.getElementById('consult-error');
  var successBox = document.getElementById('consult-success');
  var nameInput = document.getElementById('consult-name');
  var phoneInput = document.getElementById('consult-phone');
  var consentCheckbox = form.querySelector('input[name="consent"]');

  function digitsCount(value) {
    var matches = value ? value.match(/\d/g) : null;
    return matches ? matches.length : 0;
  }

  function isPhoneValid(value) {
    var allowed = /^[0-9+()\-\s]+$/.test(value.replace(/^\s+|\s+$/g, ''));
    return allowed && digitsCount(value) >= 10;
  }

  function trimToEmpty(control) {
    control.value = control.value ? control.value.replace(/^\s+|\s+$/g, '') : '';
  }

  function markInvalid(control, invalid) {
    if (invalid) {
      control.setAttribute('aria-invalid', 'true');
    } else {
      control.removeAttribute('aria-invalid');
    }
  }

  if (nameInput) {
    nameInput.addEventListener('input', function () {
      markInvalid(nameInput, false);
    });
  }

  if (phoneInput) {
    phoneInput.addEventListener('input', function () {
      markInvalid(phoneInput, false);
    });
  }

  if (consentCheckbox) {
    consentCheckbox.addEventListener('change', function () {
      markInvalid(consentCheckbox, false);
    });
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();

    var firstInvalid = null;

    if (nameInput) {
      trimToEmpty(nameInput);
      var nameOk = nameInput.value.length > 0;
      markInvalid(nameInput, !nameOk);
      if (!nameOk && !firstInvalid) {
        firstInvalid = nameInput;
      }
    }

    if (phoneInput) {
      trimToEmpty(phoneInput);
      var phoneOk = isPhoneValid(phoneInput.value);
      markInvalid(phoneInput, !phoneOk);
      if (!phoneOk && !firstInvalid) {
        firstInvalid = phoneInput;
      }
    }

    if (consentCheckbox) {
      var consentOk = consentCheckbox.checked;
      markInvalid(consentCheckbox, !consentOk);
      if (!consentOk && !firstInvalid) {
        firstInvalid = consentCheckbox;
      }
    }

    if (firstInvalid) {
      if (successBox) {
        successBox.setAttribute('hidden', '');
      }
      if (errorBox) {
        errorBox.removeAttribute('hidden');
      }
      if (typeof firstInvalid.focus === 'function') {
        firstInvalid.focus();
      }
      return;
    }

    if (errorBox) {
      errorBox.setAttribute('hidden', '');
    }
    if (successBox) {
      successBox.removeAttribute('hidden');
    }

    form.reset();

    if (nameInput) {
      markInvalid(nameInput, false);
    }
    if (phoneInput) {
      markInvalid(phoneInput, false);
    }
    if (consentCheckbox) {
      consentCheckbox.checked = false;
      markInvalid(consentCheckbox, false);
    }
  });
})();
