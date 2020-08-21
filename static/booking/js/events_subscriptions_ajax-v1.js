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
var MILLS_TO_IGNORE = 1000;


var processSubscriptionPurchaseRequest = function()  {

    //In this scope, "this" is the button just clicked on.
    //The "this" in processResult is *not* the button just clicked
    //on.
    var $button_just_clicked_on = $(this);

    //The value of the "data-event_id" attribute.
    var subscription_config_id = $button_just_clicked_on.data('subscription_config_id');
    var subscription_start_date = $button_just_clicked_on.data('subscription_start_date');
    var subscription_start_day = $button_just_clicked_on.data('subscription_start_day');
    var user_id = $button_just_clicked_on.data('user_id');

    var processResult = function(
       result, status, jqXHR)  {
      //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "'");

    $("#loader_" + subscription_config_id + '_' + user_id + "_" + subscription_start_day).removeClass("fa fa-spinner fa-spin").hide();
    $('#subscription_config_' + subscription_config_id + '_' + user_id + "_" + subscription_start_day).html(result.html);
    $('#cart_item_menu_count').text(result.cart_item_menu_count);
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
          url: '/ajax-subscription-purchase/' + subscription_config_id + '/',
          dataType: 'json',
          type: 'POST',
          data: {csrfmiddlewaretoken: window.CSRF_TOKEN, "user_id": user_id, "subscription_start_date": subscription_start_date},
          beforeSend: function() {$("#loader_" + subscription_config_id).addClass("fa fa-spinner fa-spin").show();},
          success: processResult,
          //Should also have a "fail" call as well.
          complete: function() {$("#loader_" + subscription_config_id).removeClass("fa fa-spinner fa-spin").hide();},
          error: processFailure
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
  $('.ajax_subscriptions_btn').click(_.debounce(processSubscriptionPurchaseRequest, MILLS_TO_IGNORE, true));
  /*
    Warning: Placing the true parameter outside of the debounce call:

    $('#color_search_text').keyup(_.debounce(processSearch,
        MILLS_TO_IGNORE_SEARCH), true);

    results in "TypeError: e.handler.apply is not a function".
   */

});