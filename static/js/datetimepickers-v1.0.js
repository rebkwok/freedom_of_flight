//http://xdsoft.net/jqplugins/datetimepicker/

Date.parseDate = function( input, format ){
  return moment(input,format).toDate();
};
Date.prototype.dateFormat = function( format ){
  return moment(this).format(format);
};

jQuery(document).ready(function () {

    // REGISTRATION AND DISCLAIMERS
    jQuery('#id_event_date').datetimepicker({
        format:'d-M-Y',
        formatDate:'d-M-Y',
        timepicker: false,
        closeOnDateSelect: true,
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false
    });

    jQuery('#id_date_of_birth').datetimepicker({
        format:'d-M-Y',
        formatDate:'d-M-Y',
        timepicker: false,
        defaultDate:'01-Jan-1990',
        maxDate: 0,
        closeOnDateSelect: true,
        scrollMonth: false,
        yearEnd: 2020,
        scrollTime: false,
        scrollInput: false
    });

    // STUDIOADMIN EVENT CREATE/UPDATE FORM
    jQuery('#id_start').datetimepicker({
        format:'d-M-Y H:i',
        formatTime:'H:i',
        formatDate:'d-M-Y',
        minDate: 0,
        step: 5,
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_start_open').click(function(){
        $('#id_start').datetimepicker('show');
    });

    // STUDIOADMIN CLONE FORM
    jQuery('#id_recurring_weekly_time').datetimepicker({
        datepicker:false,
        format:'H:i',
        formatTime:'H:i',
        closeOnDateSelect: true,
        step:5,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_weekly_time_open').click(function(){
        $('#id_recurring_weekly_time').datetimepicker('show');
    });

    jQuery('#id_recurring_weekly_start').datetimepicker({
        format:'d-M-Y',
        formatDate:'d-M-Y',
        timepicker: false,
        minDate: 0,
        step: 5,
        closeOnDateSelect: true,
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_weekly_start_open').click(function(){
        $('#id_recurring_weekly_start').datetimepicker('show');
    });

    jQuery('#id_recurring_weekly_end').datetimepicker({
        format:'d-M-Y',
        formatDate:'d-M-Y',
        timepicker: false,
        minDate: 0,
        step: 5,
        closeOnDateSelect: true,
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_weekly_end_open').click(function(){
        $('#id_recurring_weekly_end').datetimepicker('show');
    });

    jQuery('#id_recurring_daily_date').datetimepicker({
        format:'d-M-Y',
        formatDate:'d-M-Y',
        timepicker: false,
        minDate: 0,
        step: 5,
        closeOnDateSelect: true,
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_daily_date_open').click(function(){
        $('#id_recurring_daily_date').datetimepicker('show');
    });

    jQuery('#id_recurring_daily_starttime').datetimepicker({
        datepicker:false,
        format:'H:i',
        step:5,
        closeOnDateSelect: true,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_daily_starttime_open').click(function(){
        $('#id_recurring_daily_starttime').datetimepicker('show');
    });

    jQuery('#id_recurring_daily_endtime').datetimepicker({
        datepicker:false,
        format:'H:i',
        step:5,
        closeOnDateSelect: true,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_daily_endtime_open').click(function(){
        $('#id_recurring_daily_endtime').datetimepicker('show');
    });

    jQuery('#id_recurring_once_datetime').datetimepicker({
        format:'d-M-Y H:i',
        formatTime:'H:i',
        formatDate:'d-M-Y',
        minDate: 0,
        step: 5,
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_once_datetime_open').click(function(){
        $('#id_recurring_once_datetime').datetimepicker('show');
    });

    // TIMETABLE SESSION CREATE/UPDATE
    jQuery('#id_time').datetimepicker({
        datepicker:false,
        closeOnDateSelect: true,
        format:'H:i',
        step:5,
    });
    $('#id_time_open').click(function(){
        $('#id_time').datetimepicker('show');
    });

    // TIMETABLE UPLOAD
    jQuery('.upload_start').each(
        function (index) {
            $('#id_start_date_' + index).datetimepicker({
                format:'d-M-Y',
                formatDate:'d-M-Y',
                timepicker: false,
                minDate: 0,
                step: 5,
                closeOnDateSelect: true,
                scrollMonth: false,
                scrollTime: false,
                scrollInput: false,
            });
            $('#id_start_date_' + index + '_open').click(function(){
                $('#id_start_date_' + index).datetimepicker('show');
            });

            $('#id_end_date_' + index).datetimepicker({
                format:'d-M-Y',
                formatDate:'d-M-Y',
                timepicker: false,
                minDate: 0,
                step: 5,
                closeOnDateSelect: true,
                scrollMonth: false,
                scrollTime: false,
                scrollInput: false,
            });
            $('#id_end_date_' + index + '_open').click(function(){
                $('#id_end_date_' + index).datetimepicker('show');
            });
        }
    )

    // SUBSCRIPTON ADD/EDIT
    jQuery('#id_start_date').datetimepicker({
        format:'d-M-Y',
        formatDate:'d-M-Y',
        timepicker: false,
        closeOnDateSelect: true,
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_start_date_open').click(function(){
        $('#id_start_date').datetimepicker('show');
    });

});
