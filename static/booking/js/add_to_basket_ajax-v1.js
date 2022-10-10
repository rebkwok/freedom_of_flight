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

var processBookingAddToBasket = function()  {

    //In this scope, "this" is the button just clicked on.
    //The "this" in processResult is *not* the button just clicked
    //on.
    var $button_just_clicked_on = $(this);

    //The value of the "data-event_id" attribute.
    var event_id = $button_just_clicked_on.data('event_id');
    var user_id = $button_just_clicked_on.data('user_id');
    var ref = $button_just_clicked_on.data('ref');
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
              let contentText;
              const eventText = "<strong>" + event_str + "</strong><br/>";
              if (!cancellation_allowed) {
                  contentText = "Cancellation is not allowed; if you choose to cancel you will not receive any credit back to your block/subscription or any refund.";
              } else {
                  contentText = 'The allowed cancellation period has passed; if you choose to cancel you will not receive any credit back to your block/subscription or any refund.';
              }
              $(this).html(eventText + contentText + "<br>Please confirm you want to continue.");
            },
            buttons: [
                {
                    text: "Continue",
                    click: function () {
                        doTheAjax();
                        $(this).dialog('close');
                    },
                    "class": "btn btn-success"
                },
                {
                    text: "Go back",
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
            $('#book_' + event_id).html(result.button_html);

            $('#availability_' + event_id).html(result.event_availability_html);
            $('#availability_xs_' + event_id).html(result.event_availability_html);
            $('#event_info_xs_' + event_id).html(result.event_info_xs_html);
            $('#button_text_' + event_id).html(result.button_text);

            $('#cancelled-text-' + event_id).text("");
            $('#list-item-' + event_id).removeClass("list-group-item-secondary text-secondary");
            $('#add_to_basket_' + event_id).text("in basket");
            $('#add_course_to_basket_' + course_id).hide();
            $('#payment_options_' + event_id).hide();
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
              url: '/ajax-add-booking-to-basket/',
              dataType: 'json',
              type: 'POST',
              data: {csrfmiddlewaretoken: window.CSRF_TOKEN, "event_id": event_id, "user_id": user_id, "ref": ref},
              beforeSend: function() {$("#loader_" + event_id).addClass("fa fa-spinner fa-spin").show()},
              success: processResult,
              //Should also have a "fail" call as well.
              complete: function() {$("#loader_" + event_id).removeClass("fa fa-spinner fa-spin").hide();},
              error: processFailure
           }
       );
    }

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
  $('.ajax_add_to_basket_btn').click(_.debounce(processBookingAddToBasket, MILLS_TO_IGNORE, true));

  /*
    Warning: Placing the true parameter outside of the debounce call:

    $('#color_search_text').keyup(_.debounce(processSearch,
        MILLS_TO_IGNORE_SEARCH), true);

    results in "TypeError: e.handler.apply is not a function".
   */

});