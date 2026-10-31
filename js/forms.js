/* Прототип: реальная отправка появится на этапе подключения бэкенда */
(function () {
  'use strict';

  var form = document.getElementById('review-form');
  if (!form) {
    return;
  }

  var errorBox = document.getElementById('review-error');
  var successBox = document.getElementById('review-success');
  var textControls = form.querySelectorAll('input[type="text"], textarea');
  var consentCheckbox = form.querySelector('input[name="consent"]');

  function clearInvalidState(field) {
    field.removeAttribute('aria-invalid');
  }

  for (var i = 0; i < textControls.length; i++) {
    textControls[i].addEventListener('input', function () {
      clearInvalidState(this);
    });
  }

  if (consentCheckbox) {
    consentCheckbox.addEventListener('change', function () {
      clearInvalidState(this);
    });
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();

    var firstInvalid = null;

    for (var j = 0; j < textControls.length; j++) {
      var control = textControls[j];
      var trimmed = control.value ? control.value.replace(/^\s+|\s+$/g, '') : '';
      if (!trimmed) {
        control.value = '';
      }
      if (!control.checkValidity()) {
        control.setAttribute('aria-invalid', 'true');
        if (!firstInvalid) {
          firstInvalid = control;
        }
      } else {
        control.removeAttribute('aria-invalid');
      }
    }

    if (consentCheckbox) {
      if (!consentCheckbox.checkValidity()) {
        consentCheckbox.setAttribute('aria-invalid', 'true');
        if (!firstInvalid) {
          firstInvalid = consentCheckbox;
        }
      } else {
        consentCheckbox.removeAttribute('aria-invalid');
      }
    }

    var isFormValid = form.checkValidity() && !firstInvalid;

    if (!isFormValid) {
      if (successBox) {
        successBox.setAttribute('hidden', '');
      }
      if (errorBox) {
        errorBox.removeAttribute('hidden');
      }
      if (firstInvalid && typeof firstInvalid.focus === 'function') {
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

    for (var k = 0; k < textControls.length; k++) {
      textControls[k].removeAttribute('aria-invalid');
    }
    if (consentCheckbox) {
      consentCheckbox.checked = false;
      consentCheckbox.removeAttribute('aria-invalid');
    }
  });
})();