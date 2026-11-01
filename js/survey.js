/* Прототип: реальная отправка появится на этапе подключения бэкенда */

document.addEventListener('DOMContentLoaded', function () {
  var form = document.getElementById('quality-survey');
  if (!form) return;

  var errorAlert = document.getElementById('survey-error');
  var successAlert = document.getElementById('survey-success');

  form.addEventListener('submit', function (e) {
    e.preventDefault();

    var requiredGroups = ['q1', 'q2', 'q3', 'q4', 'q5'];
    var firstUnanswered = null;

    for (var i = 0; i < requiredGroups.length; i++) {
      var groupName = requiredGroups[i];
      var checkedOption = form.querySelector('input[name="' + groupName + '"]:checked');
      if (!checkedOption) {
        if (!firstUnanswered) {
          firstUnanswered = form.querySelector('input[name="' + groupName + '"]');
        }
      }
    }

    if (firstUnanswered) {
      if (successAlert) {
        successAlert.hidden = true;
      }
      if (errorAlert) {
        errorAlert.hidden = false;
      }
      firstUnanswered.focus();
    } else {
      if (errorAlert) {
        errorAlert.hidden = true;
      }
      if (successAlert) {
        successAlert.hidden = false;
      }
      form.reset();
    }
  });
});