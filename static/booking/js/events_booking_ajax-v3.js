/*
  This file must be imported immediately-before the close-</body> tag,
  and after JQuery and Underscore.js are imported.
*/
/**
  The number of milliseconds to ignore clicks on the *same* like
  button, after a button *that was not ignored* was clicked. Used by
  `$(document).ready()`.
  Equal to <code>500</code>.
 */
var MILLS_TO_IGNORE = 500;

var processBookingToggleRequest = function()  {

    //In this scope, "this" is the button just clicked on.
    //The "this" in processResult is *not* the button just clicked
    //on.
    var $button_just_clicked_on = $(this);

    //The value of the "data-event_id" attribute.
    var event_id = $button_just_clicked_on.data('event_id');
    var user_id = $button_just_clicked_on.data('user_id');
    var ref = $button_just_clicked_on.data('ref');
    var page = $button_just_clicked_on.data('page');
    var show_warning = $button_just_clicked_on.data('show_warning');
    var cancellation_allowed = $button_just_clicked_on.data('cancellation_allowed');

    if (show_warning) {
          $('#confirm-dialog').dialog({
            height: "auto",
            width: 500,
            modal: true,
            closeOnEscape: true,
            dialogClass: "no-close",
            title: "Warning!",
            open: function() {
              var contentText;
              if (!cancellation_allowed) {
                  contentText = "Cancellation is not allowed; if you choose to cancel you will not receive any credit back to your block/subscription or any refund.";
              } else {
                  contentText = 'The allowed cancellation period has passed; if you choose to cancel you will not receive any credit back to your block/subscription or any refund.';
              }
              $(this).html(contentText + "<br>Please confirm you want to continue.");
            },
            buttons: [
                {
                    text: "OK",
                    click: function () {
                        doTheAjax();
                        $(this).dialog('close');
                    },
                    "class": "btn btn-success"
                },
                {
                    text: "Cancel",
                    click: function () {
                        $(this).dialog('close');
                    },
                    "class": "btn btn-dark"
                }
            ]
        })
      } else {
          doTheAjax()
    }

    function doTheAjax() {

        var processResult = function(
           result, status, jqXHR)  {
          //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "'");
          if (result.redirect) {
            window.location = result.url;
          }
          else {
            $("#loader_" + event_id).removeClass("fa fa-spinner fa-spin").hide();
            $('#book_' + event_id).html(result.html);
            $('#block_info_' + event_id).html(result.block_info_html);
            $('#availability_' + event_id).html(result.event_availability_html);
            $('#availability_xs_' + event_id).html(result.event_availability_html);
            $('#event_info_xs_' + event_id).html(result.event_info_xs_html);
              if (result.just_cancelled) {
                $('#booked_tick_' + event_id).hide();
                $('#cancelled-text-' + event_id).text("You have cancelled this booking")  ;
                $('#list-item-' + event_id).addClass("list-group-item-secondary text-secondary");
              } else {
                $('#booked_tick_' + event_id).show();
                $('#cancelled-text-' + event_id).text("");
                $('#list-item-' + event_id).removeClass("list-group-item-secondary text-secondary");
              }
          }
       };

        var processFailure = function(
           result, status, jqXHR)  {
          //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "'");
          if (result.responseText) {
            vNotify.error({text:result.responseText,title:'Error',position: 'bottomRight'});
          }
       };

       $.ajax(
           {
              url: '/ajax-toggle-booking/' + event_id + '/',
              dataType: 'json',
              type: 'POST',
              data: {csrfmiddlewaretoken: window.CSRF_TOKEN, "user_id": user_id, "ref": ref, 'page': page},
              beforeSend: function() {$("#loader_" + event_id).addClass("fa fa-spinner fa-spin").show()},
              success: processResult,
              //Should also have a "fail" call as well.
              complete: function() {$("#loader_" + event_id).removeClass("fa fa-spinner fa-spin").hide();},
              error: processFailure
           }
       ).done(
           function( ) {
                $('[data-toggle="tooltip"]').tooltip();
            }
       );
    }

};

var processCourseBookingRequest = function()  {

    //In this scope, "this" is the button just clicked on.
    //The "this" in processResult is *not* the button just clicked
    //on.
    var $button_just_clicked_on = $(this);

    //The value of the "data-event_id" attribute.
    var course_id = $button_just_clicked_on.data('course_id');
    var user_id = $button_just_clicked_on.data('user_id');
    var ref = $button_just_clicked_on.data('ref');
    var page = $button_just_clicked_on.data('page');
    var allow_partial_booking = $button_just_clicked_on.data('allow_partial_booking');
    var part_booking_with_full_block = $button_just_clicked_on.data('part_booking_with_full_block');
    var has_started = $button_just_clicked_on.data('has_started');
    var has_available_block = $button_just_clicked_on.data('has_available_block');
    var already_booked = $button_just_clicked_on.data('already_booked');

    var ask_for_confirmation = function () {
        console.log(allow_partial_booking);
        if (has_started && !already_booked) {
            if (!allow_partial_booking) {
                return true
            } else if (part_booking_with_full_block) {
                return true
            } else {
                return false
            }
        } else {
            return false
        }
    };

    if (ask_for_confirmation()) {
          $('#confirm-dialog').dialog({
            height: "auto",
            width: 500,
            modal: true,
            closeOnEscape: true,
            dialogClass: "no-close",
            title: "Warning!",
            open: function() {
                var contentText;
                if (part_booking_with_full_block) {
                   contentText = "This course has already started. Your only available block is valid for a full course. Alternative blocks may be purchasable " +
                       "for booking only the remaining classes.  If you choose to book with this block, you will not receive any refund for past classes."
                } else if (has_available_block) {
                    contentText = "This course has already started. If you choose to book, you will not receive any refund for past classes."
                } else {
                    contentText = "This course has already started. If you choose to purchase a block and book this course, you will not receive any refund for past classes."
                }
                $(this).html(contentText + "<br>Please confirm you want to continue.");
            },
            buttons: [
                {
                    text: "OK",
                    click: function () {
                        doTheCourseAjax();
                        $(this).dialog('close');
                    },
                    "class": "btn btn-success"
                },
                {
                    text: "Cancel",
                    click: function () {
                        $(this).dialog('close');
                    },
                    "class": "btn btn-dark"
                }
            ]
        })
      } else {
          doTheCourseAjax()
    }

    function doTheCourseAjax () {
        var processResult = function(
           result, status, jqXHR)  {
          //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "'");
          if (result.redirect) {
            window.location = result.url;
          }
          else {
            $("#loader_" + course_id).removeClass("fa fa-spinner fa-spin").hide();
            $('#book_course_' + course_id).html(result.html);
          }
       };

        var processFailure = function(
           result, status, jqXHR)  {
          //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "'");
          if (result.responseText) {
            vNotify.error({text:result.responseText,title:'Error',position: 'bottomRight'});
          }
       };

       $.ajax(
           {
                url: '/ajax-course-booking/' + course_id + "/",
                dataType: 'json',
                type: 'POST',
                data: {csrfmiddlewaretoken: window.CSRF_TOKEN, "user_id": user_id, "ref": ref, 'page': page},
                beforeSend: function() {$("#loader_" + course_id).addClass("fa fa-spinner fa-spin").show();},
                success: processResult,
                //Should also have a "fail" call as well.
                complete: function() {$("#loader_" + course_id).removeClass("fa fa-spinner fa-spin").hide();},
                error: processFailure
           }
       );

    }
};


/**
   Executes a toggle click. Triggered by clicks on the waiting list button.
 */
var toggleWaitingList = function()  {

    //In this scope, "this" is the button just clicked on.
    //The "this" in processResult is *not* the button just clicked
    //on.
    var $button_just_clicked_on = $(this);

    //The value of the "data-event_id" attribute.
    var event_id = $button_just_clicked_on.data('event_id');
    var user_id = $button_just_clicked_on.data('user_id');

    var processResult = function(
       result, status, jqXHR)  {
      //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "', user_id='" + user_id + "'");
        $('#waiting_list_button_' + event_id).html(result);
   };

   $.ajax(
       {
          url: '/ajax-toggle-waiting-list/' + event_id + '/',
          type: 'POST',
          data: {csrfmiddlewaretoken: window.CSRF_TOKEN, "user_id": user_id},
          dataType: 'html',
          success: processResult
          //Should also have a "fail" call as well.
       }
    );
};


/**
   The Ajax "main" function. Attaches the listeners to the elements on
   page load, each of which only take effect every
   <link to MILLS_TO_IGNORE> seconds.

   This protection is only against a single user pressing buttons as fast
   as they can. This is in no way a protection against a real DDOS attack,
   of which almost 100% bypass the client (browser) (they instead
   directly attack the server). Hence client-side protection is pointless.

   - http://stackoverflow.com/questions/28309850/how-much-prevention-of-rapid-fire-form-submissions-should-be-on-the-client-side

   The protection is implemented via Underscore.js' debounce function:
  - http://underscorejs.org/#debounce

   Using this only requires importing underscore-min.js. underscore-min.map
   is not needed.
 */
$(document).ready(function()  {
  /*
    There are many buttons having the class

      td_ajax_book_button

    This attaches a listener to *every one*. Calling this again
    would attach a *second* listener to every button, meaning each
    click would be processed twice.
   */
  $('.ajax_events_btn').click(_.debounce(processBookingToggleRequest, MILLS_TO_IGNORE, true));
  $('.ajax_course_events_btn').click(_.debounce(processCourseBookingRequest, MILLS_TO_IGNORE, true));
  $('.ajax_events_waiting_list_btn').click(_.debounce(toggleWaitingList, MILLS_TO_IGNORE, true));

  $( ".event_info_popover" ).on('click', 'a', function( event ) {
    console.log("Clicked the popover");
});

  /*
    Warning: Placing the true parameter outside of the debounce call:

    $('#color_search_text').keyup(_.debounce(processSearch,
        MILLS_TO_IGNORE_SEARCH), true);

    results in "TypeError: e.handler.apply is not a function".
   */

});