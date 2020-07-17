//http://xdsoft.net/jqplugins/datetimepicker/
Date.parseDate = function( input, format ){
  return moment(input,format).toDate();
};
Date.prototype.dateFormat = function( format ){
  return moment(this).format(format);
};

jQuery(document).ready(function () {

    jQuery('#datetimepicker').datetimepicker({
        format:'DD MMM YYYY HH:mm',
        formatTime:'HH:mm',
        formatDate:'DD MM YYYY',
        minDate: 0,
        step: 5,
        defaultTime: '19:00',
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false,

    });

    jQuery('#datepicker').datetimepicker({
        format:'DD MMM YYYY',
        formatTime:'HH:mm',
        timepicker: false,
        minDate: 0,
        closeOnDateSelect: true,
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false,
    });

    jQuery('.blockdatepicker').datetimepicker({
        format:'DD MMM YYYY',
        startDate: new Date(),
        timepicker: false,
        closeOnDateSelect: true,
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false,
    });

    jQuery('#dobdatepicker').datetimepicker({
        format:'DD MMM YYYY',
        formatTime:'HH:mm',
        timepicker: false,
        defaultDate: '1990/01/01',
        closeOnDateSelect: true,
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false
    });

    // STUDIOADMIN EVENT CREATE/UPDATE FORM
    jQuery('#id_start').datetimepicker({
        format:'DD-MMM-YYYY HH:mm',
        formatTime:'HH:mm',
        formatDate:'DD-MMM-YYYY',
        minDate: 0,
        step: 5,
        defaultTime: '19:00',
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
        format:'HH:mm',
        formatTime:'HH:mm',
        step:5,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_weekly_time_open').click(function(){
        $('#id_recurring_weekly_time').datetimepicker('show');
    });

    jQuery('#id_recurring_weekly_start').datetimepicker({
        format:'DD-MMM-YYYY',
        formatDate:'DD-MMM-YYYY',
        timepicker: false,
        minDate: 0,
        step: 5,
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_weekly_start_open').click(function(){
        $('#id_recurring_weekly_start').datetimepicker('show');
    });

    jQuery('#id_recurring_weekly_end').datetimepicker({
        format:'DD-MMM-YYYY',
        formatDate:'DD-MMM-YYYY',
        timepicker: false,
        minDate: 0,
        step: 5,
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_weekly_end_open').click(function(){
        $('#id_recurring_weekly_end').datetimepicker('show');
    });

    jQuery('#id_recurring_daily_date').datetimepicker({
        format:'DD-MMM-YYYY',
        formatDate:'DD-MMM-YYYY',
        timepicker: false,
        minDate: 0,
        step: 5,
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_daily_date_open').click(function(){
        $('#id_recurring_daily_date').datetimepicker('show');
    });

    jQuery('#id_recurring_daily_starttime').datetimepicker({
        datepicker:false,
        format:'HH:mm',
        formatTime:'HH:mm',
        step:5,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_daily_starttime_open').click(function(){
        $('#id_recurring_daily_starttime').datetimepicker('show');
    });

    jQuery('#id_recurring_daily_endtime').datetimepicker({
        datepicker:false,
        format:'HH:mm',
        formatTime:'HH:mm',
        step:5,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_daily_endtime_open').click(function(){
        $('#id_recurring_daily_endtime').datetimepicker('show');
    });

    jQuery('#id_recurring_once_datetime').datetimepicker({
        format:'DD-MMM-YYYY HH:mm',
        formatTime:'HH:mm',
        formatDate:'DD-MMM-YYYY',
        minDate: 0,
        step: 5,
        defaultTime: '19:00',
        scrollMonth: false,
        scrollTime: false,
        scrollInput: false,
    });
    $('#id_recurring_once_datetime_open').click(function(){
        $('#id_recurring_once_datetime').datetimepicker('show');
    });

});
