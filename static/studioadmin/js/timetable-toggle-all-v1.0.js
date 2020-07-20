
jQuery(document).ready(function () {

    jQuery('.upload_start').each(
        function (index) {
            $("#button-id-toggle-all-" + index).click(function(){
                const checkboxes = $('input:checkbox[name="sessions_' + index + '"]');
                if (checkboxes[0].checked) {
                    checkboxes.each(function () {this.checked = false;})
                } else {
                    checkboxes.each(function () {this.checked = true;})
                }
            });
        }
    )

});
